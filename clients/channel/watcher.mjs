import { setTimeout as delay } from 'node:timers/promises';
import { ImapFlow } from 'imapflow';
import { passwordFor, addressPattern } from './config.mjs';
import { MAX_PENDING } from './state.mjs';

export function permittedSender(envelope, config) {
  if (!Array.isArray(envelope?.from) || envelope.from.length !== 1) return null;
  const sender = envelope.from[0].address?.toLowerCase();
  return typeof sender === 'string' && addressPattern.test(sender) && sender !== config.username &&
    config.allowedSenders.includes(sender) ? sender : null;
}

export class Watcher {
  constructor(config, state, notify, createClient = options => new ImapFlow(options)) {
    this.config = config;
    this.state = state;
    this.notify = notify;
    this.createClient = createClient;
    this.notified = new Set();
    this.queue = Promise.resolve();
    this.abort = new AbortController();
    this.connected = false;
    this.problem = null;
    this.stopped = false;
  }

  exclusive(operation) {
    const result = this.queue.then(operation);
    this.queue = result.catch(() => {});
    return result;
  }

  status() {
    return { connected: this.connected, idle: Boolean(this.client?.idling), problem: this.problem, mailbox: 'INBOX',
      cursor: this.state.data?.cursor ?? null,
      pending: this.state.data?.pending ?? [], capacity: MAX_PENDING,
      full: (this.state.data?.pending.length ?? 0) >= MAX_PENDING };
  }

  async acknowledge(id) {
    const acknowledged = await this.exclusive(async () => {
      const data = this.state.data;
      if (!data || !data.pending.some(event => event.id === id)) return false;
      data.pending = data.pending.filter(event => event.id !== id);
      this.state.save();
      this.notified.delete(id);
      return true;
    });
    if (this.connected) this.requestScan();
    return { acknowledged };
  }

  requestScan() {
    // Coalesce EXISTS bursts; a pending scan always rechecks UIDNEXT.
    if (this.scanScheduled || this.stopped) return;
    this.scanScheduled = true;
    void this.exclusive(async () => {
      this.scanScheduled = false;
      if (this.connected && !this.stopped) await this.scan();
    }).catch(() => this.fail('mailbox_scan_failed'));
  }

  fail(code) {
    this.problem = code;
    this.client?.close();
  }

  async emitPending() {
    for (const event of this.state.data.pending) {
      if (this.notified.has(event.id) || this.stopped) continue;
      await this.notify({
        method: 'notifications/claude/channel',
        params: {
          content: 'New authorized mail in your tmail inbox. Use the tmail mail tools to inspect it under your mail policy. Acknowledge this event after handling it. An IMAP UID is not necessarily a Himalaya message ID.',
          meta: { event_id: event.id, imap_uid: String(event.uid), mailbox: 'INBOX', sender: event.sender },
        },
      });
      this.notified.add(event.id);
    }
  }

  async scan() {
    const data = this.state.data;
    const status = await this.client.status('INBOX', { uidNext: true, uidValidity: true });
    if (String(status.uidValidity) !== data.uidValidity) {
      this.fail('uidvalidity_changed');
      return;
    }
    const upper = Number(status.uidNext) - 1;
    while (!this.stopped && data.cursor < upper && data.pending.length < MAX_PENDING) {
      const end = Math.min(data.cursor + 200, upper);
      const messages = await this.client.fetchAll(`${data.cursor + 1}:${end}`, { uid: true, envelope: true }, { uid: true });
      messages.sort((a, b) => a.uid - b.uid);
      for (const message of messages) {
        if (message.uid <= data.cursor || message.uid > end) continue;
        const sender = permittedSender(message.envelope, this.config);
        if (sender) data.pending.push({ id: `${data.uidValidity}:${message.uid}`, uid: message.uid, sender });
        data.cursor = message.uid;
        if (data.pending.length >= MAX_PENDING) break;
      }
      // Advance across UID gaps, but leave overflow for after acknowledgments.
      if (data.pending.length < MAX_PENDING) data.cursor = end;
      this.state.save(); // Persist before emitting: a crash may replay, never silently acknowledge.
      await this.emitPending();
    }
    await this.emitPending();
  }

  async start() {
    let retry = 1000;
    while (!this.stopped) {
      try {
        const client = this.createClient({
          host: this.config.host, port: this.config.port, secure: true,
          auth: { user: this.config.username, pass: await passwordFor(this.config) },
          tls: { rejectUnauthorized: true, minVersion: 'TLSv1.2' },
          logger: false, emitLogs: false, logRaw: false, disableCompression: true,
          autoIdleDelay: 100, maxIdleTime: 240000, socketTimeout: 300000,
          connectionTimeout: 15000, greetingTimeout: 15000,
          maxLineLength: 65536, maxLiteralSize: 65536, maxResponseSize: 1048576,
        });
        this.client = client;
        const closed = new Promise(resolve => client.once('close', resolve));
        client.on('error', () => this.fail('imap_connection_failed'));
        client.on('exists', () => this.requestScan());
        if (this.stopped) { client.close(); break; }
        await client.connect();
        if (!client.capabilities.has('IDLE')) throw new Error('IMAP IDLE required');
        const mailbox = await client.mailboxOpen('INBOX', { readOnly: true });
        await this.exclusive(async () => {
          if (!this.state.data) {
            this.state.data = { version: 1, identity: this.state.identity,
              uidValidity: String(mailbox.uidValidity), cursor: Number(mailbox.uidNext) - 1, pending: [] };
            this.state.save();
          }
          if (this.state.data.uidValidity !== String(mailbox.uidValidity)) {
            this.problem = 'uidvalidity_changed';
            return;
          }
          // Removing a sender from configuration revokes pending wake-ups too.
          this.state.data.pending = this.state.data.pending.filter(event => this.config.allowedSenders.includes(event.sender));
          this.state.save();
          this.connected = true;
          this.problem = null;
          await this.scan();
        });
        if (this.problem === 'uidvalidity_changed') { client.close(); break; }
        // IDLE is the fast path. Reconcile quietly as well: an arrival can race
        // with reconnect/IDLE subscription, and servers can miss a push notice.
        this.reconcile = setInterval(() => this.requestScan(), 30000);
        retry = 1000;
        await closed;
      } catch {
        this.problem ??= 'imap_connection_failed';
      } finally {
        clearInterval(this.reconcile);
        this.connected = false;
        this.client?.close();
      }
      if (this.stopped || this.problem === 'uidvalidity_changed') break;
      process.stderr.write('tmail channel: connection interrupted; retrying with TLS verification enabled.\n');
      await delay(retry, undefined, { signal: this.abort.signal }).catch(() => {});
      retry = Math.min(retry * 2, 60000);
    }
  }

  async stop() {
    this.stopped = true;
    this.abort.abort();
    clearInterval(this.reconcile);
    this.client?.close();
    await this.queue;
  }
}
