"""Real IMAP IDLE + MCP notification tests, isolated from live mail and Tailscale."""
from pathlib import Path
import os
import queue
import threading

os.umask(0o077)
# Reuse the synthetic Stalwart fixture, not its separate acceptance-test body.
exec(Path('/tests/integration.py').read_text().split('\ntry:\n    start()\n')[0], globals())


class Bridge:
    def __init__(self, config, ca=True):
        self.events = []
        self.messages = queue.Queue()
        self.sequence = 0
        self.logfile = ROOT / f'channel-{secrets.token_hex(4)}.log'
        self.log = self.logfile.open('w')
        env = dict(os.environ)
        env.pop('NODE_EXTRA_CA_CERTS', None)
        if ca:
            env['NODE_EXTRA_CA_CERTS'] = str(ROOT / 'ca.pem')
        self.process = subprocess.Popen(['node', '/channel/server.mjs', '--config', str(config)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, env=env)
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    def read(self):
        for line in self.process.stdout:
            self.messages.put(json.loads(line))
        self.messages.put(None)

    def write(self, value):
        self.process.stdin.write(json.dumps(value) + '\n')
        self.process.stdin.flush()

    def rpc(self, method, params):
        self.sequence += 1
        self.write({'jsonrpc': '2.0', 'id': self.sequence, 'method': method, 'params': params})
        while True:
            result = self.messages.get(timeout=15)
            assert result is not None, 'Channel exited unexpectedly'
            if result.get('method') == 'notifications/claude/channel':
                self.events.append(result)
                continue
            assert result.get('id') == self.sequence and 'error' not in result, result
            return result['result']

    def initialize(self):
        result = self.rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'tmail-channel-test', 'version': '1'}})
        assert result['capabilities']['experimental']['claude/channel'] == {}
        self.write({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return result

    def tool(self, name, arguments=None):
        result = self.rpc('tools/call', {'name': name, 'arguments': arguments or {}})
        assert not result.get('isError'), result
        return json.loads(result['content'][0]['text'])

    def wait_status(self, predicate):
        for _ in range(100):
            status = self.tool('channel_status')
            if predicate(status):
                return status
            time.sleep(.1)
        raise AssertionError('Channel status did not converge')

    def event(self, timeout=10):
        if self.events:
            return self.events.pop(0)
        try:
            result = self.messages.get(timeout=timeout)
        except queue.Empty:
            raise AssertionError(f'No channel event: {self.tool("channel_status")}; inbox count={len(inbox("alpha"))}') from None
        assert result and result.get('method') == 'notifications/claude/channel', result
        return result

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        self.reader.join(timeout=2)
        self.log.close()
        assert not any(password in self.logfile.read_text() for password in PASSWORDS.values()), 'Secret in channel logs'


bridges = []
def launch(config, ca=True):
    instance = Bridge(config, ca)
    bridges.append(instance)
    instance.initialize()
    return instance

try:
    start()
    domain = next(d['id'] for d in objects('Domain') if d['name'] == 'tmail.internal')
    for name in ('alpha', 'beta'):
        create('Account', {'@type': 'User', 'name': name, 'domainId': domain,
            'roles': {'@type': 'User'}, 'credentials': {'0': {'@type': 'Password', 'secret': PASSWORDS[name]}},
            'quotas': {'maxDiskQuota': 1073741824}})
    create('MemoryLookupKey', {'namespace': 'tmail-peers', 'key': 'beta@tmail.internal|alpha@tmail.internal',
                             'isGlobPattern': False})
    action('ReloadLookupStores')
    password_file = ROOT / 'channel-password'
    password_file.write_text(PASSWORDS['alpha'])
    config = {'host': HOST, 'port': 1993, 'username': 'alpha@tmail.internal',
        'passwordFile': str(password_file), 'allowedSenders': ['owner@tmail.internal'],
        'stateDirectory': str(ROOT / 'channel-state')}
    config_file = ROOT / 'channel.json'
    config_file.write_text(json.dumps(config))

    send('owner', 'alpha')
    for _ in range(50):
        if len(inbox('alpha')) == 1:
            break
        time.sleep(.1)
    bridge = launch(config_file)
    bridge.wait_status(lambda status: status['connected'])
    tools = bridge.rpc('tools/list', {})['tools']
    check({tool['name'] for tool in tools} == {'channel_status', 'channel_ack'},
          'channel advertises Claude capability and only local status/ack tools')
    check(bridge.tool('channel_status')['pending'] == [], 'first connection skips existing mail history')
    time.sleep(.5)  # Let ImapFlow enter IDLE, then send without a client tool call.
    send('owner', 'alpha')
    event = bridge.event()
    check(event['params']['meta']['imap_uid'] == '2', 'real SMTP delivery produces an unsolicited IMAP IDLE channel event')
    check('Subject' not in json.dumps(event) and 'tmail isolated test' not in json.dumps(event),
          'notification omits email subjects and bodies')
    client = imaplib.IMAP4_SSL(host=HOST, port=1993, ssl_context=TLS, timeout=10)
    client.login('alpha@tmail.internal', PASSWORDS['alpha'])
    client.select('INBOX', readonly=True)
    status, flags = client.uid('fetch', '2', '(FLAGS)')
    client.logout()
    check(status == 'OK' and b'\\Seen' not in b''.join(x for x in flags if isinstance(x, bytes)),
          'watching and envelope inspection leave mail unread')
    check(bridge.tool('channel_ack', {'event_id': event['params']['meta']['event_id']})['acknowledged'],
          'agent acknowledgment removes the durable pending event')
    send('beta', 'alpha')
    time.sleep(.5)
    check(bridge.tool('channel_status')['pending'] == [] and not bridge.events,
          'server-authorized peer cannot wake the agent unless also in the channel allowlist')

    send('owner', 'alpha')
    pending = bridge.event()['params']['meta']['event_id']
    bridge.close()
    send('owner', 'alpha')
    bridge = launch(config_file)
    bridge.wait_status(lambda status: status['connected'] and len(status['pending']) == 2)
    events = [bridge.event(), bridge.event()]
    check(events[0]['params']['meta']['event_id'] == pending and len({e['params']['meta']['event_id'] for e in events}) == 2,
          'restart replays pending work and delivers mail received while the bridge was stopped')
    for item in events:
        bridge.tool('channel_ack', {'event_id': item['params']['meta']['event_id']})
    bridge.close()
    bridge = launch(config_file)
    bridge.wait_status(lambda status: status['connected'])
    check(bridge.tool('channel_status')['pending'] == [], 'acknowledged events stay acknowledged across restarts')

    duplicate = Bridge(config_file)
    bridges.append(duplicate)
    check(duplicate.process.wait(timeout=5) != 0, 'second session cannot consume the same channel state concurrently')
    stop()
    bridge.wait_status(lambda status: not status['connected'])
    start()
    bridge.wait_status(lambda status: status['connected'])
    send('owner', 'alpha')
    check(bridge.event(timeout=40)['params']['meta']['sender'] == 'owner@tmail.internal',
          'reconnect reconciliation catches arrival racing with a real server restart')

    for label, extra, trust in [('untrusted', {}, False), ('wrong-host', {'host': 'tmail.wrong.ts.net'}, True)]:
        invalid_config = ROOT / f'{label}.json'
        invalid_config.write_text(json.dumps({**config, **extra, 'stateDirectory': str(ROOT / label)}))
        invalid = launch(invalid_config, ca=trust)
        status = invalid.wait_status(lambda status: status['problem'] is not None)
        check(not status['connected'] and not status['pending'], f'channel rejects {label} TLS without plaintext fallback')
        invalid.close()
    check((Path(config['stateDirectory']) / 'state.json').stat().st_mode & 0o777 == 0o600,
          'durable channel state is owner-only')
    print(f'{checks} channel integration checks passed', flush=True)
finally:
    for bridge in bridges:
        bridge.close()
    if process and process.poll() is None:
        stop()
