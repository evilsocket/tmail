"""Drive only a unique synthetic Docker project; no real mail or enrollment keys."""
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import subprocess
import threading
import time

root = Path('/workspace')
host_root = os.environ['TMAIL_TEST_HOST_WORK']
repo = os.environ['TMAIL_TEST_HOST_REPO']
name = 'test-' + secrets.token_hex(5)
checks = 0
processes = []


def check(condition, label):
    global checks
    assert condition, label
    checks += 1
    print('PASS ' + label, flush=True)


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'Test command failed: {result.stderr}')
    return result.stdout


def until(predicate, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.2)
    raise AssertionError('Timed out waiting for test fixture')


class MCP:
    def __init__(self, service):
        self.events = []
        self.messages = queue.Queue()
        self.sequence = 0
        self.log = (root / (service + '.stderr')).open('w')
        self.process = subprocess.Popen(compose + ['run', '--rm', '-T', '--no-deps', service],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.log, text=True)
        processes.append(self)
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
        self.rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                               'clientInfo': {'name': 'container-test', 'version': '1'}})
        self.write({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        finally:
            self.messages.put(None)

    def write(self, value):
        self.process.stdin.write(json.dumps(value) + '\n')
        self.process.stdin.flush()

    def rpc(self, method, params):
        self.sequence += 1
        self.write({'jsonrpc': '2.0', 'id': self.sequence, 'method': method, 'params': params})
        while True:
            response = self.messages.get(timeout=30)
            if response is None:
                self.log.flush()
                diagnosis = subprocess.run(compose + ['run', '--rm', '-T', '--no-deps',
                    '--entrypoint', 'node', 'events', '--input-type=module', '-e', '''
import fs from 'node:fs';
import {privateRead, validateConfig} from '/channel/config.mjs';
import {State} from '/channel/state.mjs';
console.error('UID', process.getuid());
for (const path of ['/config/channel.json','/config/password','/state']) {
  const s=fs.lstatSync(path); console.error(path, s.uid, (s.mode & 511).toString(8));
}
const config=validateConfig(JSON.parse(privateRead('/config/channel.json')));
const state=await State.open(config); await state.release();
'''], capture_output=True, text=True)
                print(diagnosis.stderr, flush=True)
                raise AssertionError(Path(self.log.name).read_text())
            if response.get('method') == 'notifications/claude/channel':
                self.events.append(response)
                continue
            assert response.get('id') == self.sequence and 'error' not in response, response
            return response['result']

    def tool(self, name, arguments=None):
        result = self.rpc('tools/call', {'name': name, 'arguments': arguments or {}})
        assert not result.get('isError'), result
        return result

    def status(self):
        return json.loads(self.tool('channel_status')['content'][0]['text'])

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=15)
        self.log.close()


run('/opt/tmail/scripts/setup-server-container.sh', 'tmail.test.ts.net')
old_secret = (root / '.secrets/blob_key').read_bytes()
run('/opt/tmail/scripts/setup-server-container.sh', 'tmail.test.ts.net')
check(old_secret == (root / '.secrets/blob_key').read_bytes(), 'containerized server setup preserves secrets on rerun')
run('/opt/tmail/scripts/setup-client-container.sh', 'tmail.test.ts.net', 'alpha', name)
client = root / '.clients' / name
config = client / 'mail'
(config / 'password').write_text('preserve-this-placeholder')
run('/opt/tmail/scripts/setup-client-container.sh', 'tmail.test.ts.net', 'alpha', name)
check((config / 'password').read_text() == 'preserve-this-placeholder', 'containerized client setup preserves existing mailbox configuration')
# Exercise the production bridge as a non-root file owner, independent of the
# test controller's Docker-socket privileges.
env_file = client / 'client.env'
env_file.write_text(env_file.read_text().replace('TMAIL_CLIENT_UID=0', 'TMAIL_CLIENT_UID=2000')
                    .replace('TMAIL_CLIENT_GID=0', 'TMAIL_CLIENT_GID=2000'))
shutil.copy('/compose.client.yaml', root / 'compose.client.yaml')
shared = root / 'shared'
shared.mkdir(mode=0o777)
shared.chmod(0o777)
(root / 'containerboot').write_text('#!/bin/sh\ntrap "exit 0" TERM INT\nwhile :; do sleep 1 & wait $!; done\n')
(root / 'tailscale').write_text('''#!/bin/sh
set -eu
case "$1" in --socket=*) shift;; esac
case "$1" in
  status) echo '{"BackendState":"Running"}';;
  nc)
    [ "$2" = tmail.test.ts.net ]
    case "$3" in 993) port=1993;; 465) port=1465;; *) exit 1;; esac
    exec socat STDIO "TCP4:fixture:$port";;
  *) exit 1;;
esac
''')
for filename in ('containerboot', 'tailscale'):
    (root / filename).chmod(0o755)
override = {'services': {
    'gateway': {'volumes': [f'{host_root}/containerboot:/usr/local/bin/containerboot:ro',
                            f'{host_root}/tailscale:/usr/local/bin/tailscale:ro']},
    'events': {'environment': {'NODE_EXTRA_CA_CERTS': '/config/ca.pem'}},
    'fixture': {'image': 'tmail-test:local', 'entrypoint': ['python3', '/tests/client-fixture.py'],
                'networks': ['backend'], 'read_only': True, 'cap_drop': ['ALL'],
                'security_opt': ['no-new-privileges:true'], 'mem_limit': '2g',
                'extra_hosts': ['tmail.test.ts.net:127.0.0.1'],
                'volumes': [f'{repo}/tests:/tests:ro', f'{host_root}/shared:/shared'],
                'tmpfs': [f'{path}:uid=2000,gid=2000' for path in
                          ('/tmp', '/run/tmail', '/run/secrets', '/var/lib/stalwart',
                           '/etc/stalwart', '/certificates', '/var/cache/tmail')]}},
    'networks': {'internet': {'internal': True}}}
(root / 'override.json').write_text(json.dumps(override))
# Compose sees host paths so sibling bind mounts refer to this synthetic directory.
compose = ['docker', 'compose', '--project-directory', host_root, '--env-file', str(client / 'client.env'),
           '-f', str(root / 'compose.client.yaml'), '-f', str(root / 'override.json')]
smoke = name + '-gateway-smoke'
try:
    smoke_args = ['docker', 'run', '-d', '--name', smoke, '--network', 'none', '--read-only',
                  '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                  '--pids-limit', '128', '--memory', '256m']
    for path in ('/tmp', '/var/run/tailscale', '/var/lib/tailscale', '/run/secrets'):
        smoke_args += ['--tmpfs', path]
    for key, value in {'TMAIL_HOSTNAME': 'tmail.test.ts.net', 'TMAIL_GATEWAY_BIND': '127.0.0.1',
                       'TS_SOCKET': '/var/run/tailscale/tailscaled.sock', 'TS_USERSPACE': 'true',
                       'TS_STATE_DIR': '/var/lib/tailscale', 'TS_AUTH_ONCE': 'true',
                       'TS_ACCEPT_DNS': 'false', 'TS_NO_LOGS_NO_SUPPORT': 'true'}.items():
        smoke_args += ['-e', f'{key}={value}']
    run(*smoke_args, '--entrypoint', 'sh', 'tmail-client-gateway:local', '-c',
        ': > /run/secrets/tailscale_authkey; exec /opt/tmail/client-gateway.sh')
    def needs_login():
        result = subprocess.run(['docker', 'exec', smoke, 'tailscale', 'status', '--json'],
                                capture_output=True, text=True)
        try:
            return json.loads(result.stdout).get('BackendState') == 'NeedsLogin'
        except ValueError:
            return False
    until(needs_login, timeout=30)
    check(True, 'real userspace client gateway starts without TUN, capabilities, network, or enrollment')
    run('docker', 'rm', '-f', smoke)
    rendered = json.loads(run(*compose, '--profile', 'mcp', 'config', '--format', 'json'))
    check(not any(service.get('ports') or service.get('privileged') for service in rendered['services'].values()),
          'client Compose publishes no ports and requires no privileged containers')
    check(rendered['services']['mail']['networks'] == {'backend': None} and
          rendered['services']['mail']['user'] == '2000:2000' and
          not rendered['services']['mail'].get('secrets') and
          len(rendered['services']['mail']['volumes']) == 1,
          'non-root mail bridge receives only its config mount and internal network')
    run(*compose, 'up', '-d', 'fixture', 'gateway')
    until(lambda: (shared / 'ready').exists())
    (config / 'password').write_text((shared / 'password').read_text())
    shutil.copy(shared / 'ca.pem', config / 'ca.pem')
    himalaya = (config / 'himalaya.toml').read_text()
    himalaya += '\nimap.tls.cert = "/config/ca.pem"\nsmtp.tls.cert = "/config/ca.pem"\n'
    (config / 'himalaya.toml').write_text(himalaya)
    for path in [config, *config.iterdir(), client / 'state']:
        os.chown(path, 2000, 2000)
    events = MCP('events')
    until(lambda: events.status()['connected'])
    check(events.status()['pending'] == [], 'production event container connects through the gateway and skips existing mail')
    mail = MCP('mail')
    tools = {tool['name'] for tool in mail.rpc('tools/list', {})['tools']}
    check({'message_send', 'message_reply', 'message_read', 'envelope_list'} <= tools and
          not any('delete' in tool or 'move' in tool for tool in tools),
          'production mail container advertises read/send/reply without destructive tools')
    mail.tool('envelope_list')
    mail.tool('message_read', {'id': '1'})
    check(True, 'production MCP reads synthetic mail over verified TLS through the gateway')
    mail.tool('message_reply', {'id': '1', 'body': 'Synthetic Docker reply', 'send': True})
    mail.tool('message_send', {'message': ['From: alpha@tmail.internal\r\nTo: owner@tmail.internal\r\nSubject: Docker test\r\n\r\nSynthetic test\r\n']})
    check(True, 'production MCP sends and replies through gateway SMTP with verified TLS')
    time.sleep(.5)
    (shared / 'deliver').touch()
    event = events.messages.get(timeout=20)
    check(event and event.get('method') == 'notifications/claude/channel',
          'production event container emits an unsolicited event after SMTP delivery')
    check('tmail isolated test' not in json.dumps(event) and 'private dummy' not in json.dumps(event),
          'Docker stdio event excludes subject and body')
    event_id = event['params']['meta']['event_id']
    events.close()
    events = MCP('events')
    until(lambda: events.status()['connected'])
    check(any(item['id'] == event_id for item in events.status()['pending']),
          'pending event survives container removal and replay')
    events.tool('channel_ack', {'event_id': event_id})
    events.close()
    events = MCP('events')
    until(lambda: events.status()['connected'])
    check(events.status()['pending'] == [], 'event acknowledgment survives container recreation')
    events.close()
    mail.close()
    check(not run(*compose, 'ps', '-aq', 'mail', 'events').strip(), 'stdio EOF removes on-demand MCP containers cleanly')
    print(f'{checks} production client-container checks passed', flush=True)
finally:
    subprocess.run(['docker', 'rm', '-f', smoke], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for process in processes:
        if process.process.poll() is None:
            process.process.terminate()
    run(*compose, '--profile', 'mcp', 'down', '-v', '--remove-orphans')
