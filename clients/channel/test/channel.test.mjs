import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { passwordFor, privateRead, validateConfig } from '../config.mjs';
import { State, MAX_PENDING } from '../state.mjs';
import { permittedSender, Watcher } from '../watcher.mjs';

function fixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'tmail-channel-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const passwordFile = path.join(directory, 'password');
  fs.writeFileSync(passwordFile, 'dummy-test-secret\n', { mode: 0o600 });
  return { host: 'tmail.test.ts.net', port: 993, username: 'agent@tmail.internal', passwordFile,
    allowedSenders: ['owner@tmail.internal'], stateDirectory: path.join(directory, 'state') };
}

async function until(predicate) {
  for (let i = 0; i < 250; i++) {
    if (predicate()) return;
    await delay(20);
  }
  assert.fail('Condition did not become true');
}

class FakeImap extends EventEmitter {
  constructor(mailbox, options) {
    super();
    this.data = mailbox;
    this.options = options;
    this.capabilities = new Set(['IDLE']);
  }
  async connect() {}
  async mailboxOpen(name, options) {
    assert.equal(name, 'INBOX');
    assert.equal(options.readOnly, true);
    return this.status();
  }
  async status() { return { uidNext: this.data.next, uidValidity: BigInt(this.data.validity) }; }
  async fetchAll(range, query, options) {
    assert.deepEqual(query, { uid: true, envelope: true });
    assert.deepEqual(options, { uid: true });
    const [low, high] = range.split(':').map(Number);
    return this.data.messages.filter(message => message.uid >= low && message.uid <= high);
  }
  close() { if (!this.closed) { this.closed = true; this.emit('close'); } }
}

async function watching(config, mailbox) {
  const state = await State.open(config);
  const events = [];
  const clients = [];
  const watcher = new Watcher(config, state, async event => events.push(event), options => {
    const client = new FakeImap(mailbox, options);
    clients.push(client);
    return client;
  });
  const task = watcher.start();
  return { state, events, watcher, clients, close: async () => {
    await watcher.stop(); await task; await state.release();
  } };
}

const message = (uid, sender = 'owner@tmail.internal') => ({ uid,
  envelope: { from: [{ address: sender }], subject: 'private subject must never be emitted' } });

test('configuration rejects insecure options, wildcard senders and privileged mailboxes', t => {
  const config = fixture(t);
  assert.deepEqual(validateConfig(config), config);
  for (const change of [{ tls: { rejectUnauthorized: false } }, { host: 'example.com' },
    { username: 'admin@tmail.internal' }, { username: 'maintenance@tmail.internal' },
    { allowedSenders: ['*@tmail.internal'] }, { port: 0 }, { passwordCommand: ['/bin/cat', config.passwordFile] }]) {
    assert.throws(() => validateConfig({ ...config, ...change }));
  }
});

test('password files must be private; password commands are argv, never a shell', async t => {
  const config = fixture(t);
  assert.equal(await passwordFor(config), 'dummy-test-secret');
  fs.chmodSync(config.passwordFile, 0o644);
  assert.throws(() => privateRead(config.passwordFile));
  fs.chmodSync(config.passwordFile, 0o600);
  assert.equal(await passwordFor({ passwordCommand: [process.execPath, '-e', 'process.stdout.write("literal;$(no-shell)")'] }), 'literal;$(no-shell)');
});

test('only a single exact allowed sender can wake the agent; self-mail is suppressed', t => {
  const config = fixture(t);
  assert.equal(permittedSender(message(1).envelope, config), 'owner@tmail.internal');
  for (const envelope of [message(1, 'other@tmail.internal').envelope, { from: [] },
    { from: [{ address: 'owner@tmail.internal' }, { address: 'other@tmail.internal' }] },
    { from: [{ address: 'owner@tmail.internal.evil' }] }, message(1, config.username).envelope]) {
    assert.equal(permittedSender(envelope, config), null);
  }
});

test('state excludes a second watcher and refuses corrupt or mismatched identity', async t => {
  const config = fixture(t);
  const first = await State.open(config);
  await assert.rejects(State.open(config));
  first.data = { version: 1, identity: first.identity, uidValidity: '1', cursor: 0, pending: [] };
  first.save();
  assert.equal(fs.statSync(first.filename).mode & 0o777, 0o600);
  await first.release();
  await assert.rejects(State.open({ ...config, username: 'another@tmail.internal' }));
  fs.writeFileSync(first.filename, '{invalid');
  await assert.rejects(State.open(config));
});

test('IDLE events deliver new allowed mail without bodies, deduplicate and acknowledge', async t => {
  const config = fixture(t);
  const mailbox = { validity: 5, next: 2, messages: [message(1)] };
  const run = await watching(config, mailbox);
  t.after(run.close);
  await until(() => run.watcher.connected);
  assert.equal(run.state.data.cursor, 1);
  assert.equal(run.events.length, 0); // Initial history is deliberately not replayed.
  mailbox.messages.push(message(2), message(3, 'unapproved@tmail.internal'));
  mailbox.next = 4;
  run.clients[0].emit('exists');
  run.clients[0].emit('exists');
  await until(() => run.state.data.cursor === 3);
  assert.equal(run.events.length, 1);
  assert.equal(run.events[0].method, 'notifications/claude/channel');
  assert.equal(run.events[0].params.meta.event_id, '5:2');
  assert.ok(!JSON.stringify(run.events).includes('private subject'));
  assert.deepEqual(run.clients[0].options.tls, { rejectUnauthorized: true, minVersion: 'TLSv1.2' });
  assert.equal(run.clients[0].options.secure, true);
  assert.equal(run.clients[0].options.logger, false);
  assert.deepEqual(await run.watcher.acknowledge('5:2'), { acknowledged: true });
  assert.deepEqual(await run.watcher.acknowledge('5:2'), { acknowledged: false });
  assert.equal(run.state.data.pending.length, 0);
});

test('restart replays unacknowledged events and catches offline delivery; revoked senders are removed', async t => {
  const config = fixture(t);
  const mailbox = { validity: 7, next: 1, messages: [] };
  let run = await watching(config, mailbox);
  await until(() => run.watcher.connected);
  mailbox.messages.push(message(1)); mailbox.next = 2; run.clients[0].emit('exists');
  await until(() => run.events.length === 1);
  await run.close();
  mailbox.messages.push(message(2)); mailbox.next = 3;
  run = await watching(config, mailbox);
  await until(() => run.events.length === 2);
  assert.deepEqual(run.events.map(event => event.params.meta.event_id), ['7:1', '7:2']);
  await run.watcher.acknowledge('7:1');
  await run.close();
  run = await watching({ ...config, allowedSenders: [] }, mailbox);
  t.after(run.close);
  await until(() => run.watcher.connected);
  assert.equal(run.events.length, 0);
  assert.equal(run.state.data.pending.length, 0);
});

test('full notification queue retains unread work until acknowledgments free space', async t => {
  const config = fixture(t);
  const mailbox = { validity: 9, next: 1, messages: [] };
  const run = await watching(config, mailbox);
  t.after(run.close);
  await until(() => run.watcher.connected);
  mailbox.messages = Array.from({ length: MAX_PENDING + 5 }, (_, index) => message(index + 1));
  mailbox.next = MAX_PENDING + 6;
  run.clients[0].emit('exists');
  await until(() => run.events.length === MAX_PENDING);
  assert.equal(run.watcher.status().full, true);
  assert.equal(run.state.data.cursor, MAX_PENDING);
  for (let uid = 1; uid <= 5; uid++) await run.watcher.acknowledge(`9:${uid}`);
  await until(() => run.events.length === MAX_PENDING + 5);
  assert.equal(run.state.data.cursor, MAX_PENDING + 5);
  assert.equal(run.state.data.pending.length, MAX_PENDING);
});

test('reconnect catches missed EXISTS; UIDVALIDITY changes stop delivery without erasing state', async t => {
  const config = fixture(t);
  const mailbox = { validity: 11, next: 1, messages: [] };
  const run = await watching(config, mailbox);
  t.after(run.close);
  await until(() => run.watcher.connected);
  run.clients[0].close();
  mailbox.messages.push(message(1)); mailbox.next = 2;
  await until(() => run.clients.length === 2 && run.events.length === 1);
  mailbox.validity = 12;
  run.clients[1].emit('exists');
  await until(() => run.watcher.problem === 'uidvalidity_changed');
  assert.equal(run.state.data.uidValidity, '11');
  assert.equal(run.state.data.pending.length, 1);
});

test('MCP handshake advertises channels, waits for initialization, and exits on stdin EOF', async t => {
  const config = fixture(t);
  const configFile = path.join(path.dirname(config.passwordFile), 'config.json');
  fs.writeFileSync(configFile, JSON.stringify(config), { mode: 0o600 });
  const child = spawn(process.execPath, [fileURLToPath(new URL('../server.mjs', import.meta.url)), '--config', configFile],
    { stdio: ['pipe', 'pipe', 'pipe'] });
  t.after(() => child.kill());
  let stderr = '';
  child.stderr.on('data', chunk => { stderr += chunk; });
  const lines = createInterface({ input: child.stdout });
  const response = once(lines, 'line');
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: {
    protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'test', version: '1' },
  } }) + '\n');
  const [line] = await response;
  assert.deepEqual(JSON.parse(line).result.capabilities.experimental['claude/channel'], {});
  assert.equal(fs.existsSync(path.join(config.stateDirectory, 'state.json')), false);
  const exited = once(child, 'exit');
  child.stdin.end();
  assert.deepEqual(await exited, [0, null]);
  assert.equal(stderr, '');
  assert.equal(fs.existsSync(config.stateDirectory + '.lock'), false);
});
