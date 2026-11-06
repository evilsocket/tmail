"""Black-box acceptance tests. Run only through tests/run.sh, in network-none Docker."""
import base64
import email.message
import http.client
import imaplib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import smtplib
import socket
import ssl
import struct
import subprocess
import time

HOST = 'tmail.test.ts.net'
ROOT = Path('/tmp/tmail-tests')
ROOT.mkdir()
PASSWORDS = {name: secrets.token_urlsafe(32) for name in ('admin', 'owner', 'maintenance', 'alpha', 'beta')}
process = None
checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1
    print(f'PASS {message}', flush=True)


def run(*args, **kw):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kw).stdout


def issue_cert(directory, serial):
    directory.mkdir(parents=True, exist_ok=True)
    run('openssl', 'req', '-new', '-newkey', 'rsa:2048', '-noenc', '-subj', f'/CN={HOST}',
        '-keyout', str(directory / 'privkey.pem'), '-out', str(ROOT / 'leaf.csr'))
    (ROOT / 'ext.cnf').write_text(f'subjectAltName=DNS:{HOST}\nextendedKeyUsage=serverAuth\n')
    run('openssl', 'x509', '-req', '-in', str(ROOT / 'leaf.csr'), '-CA', str(ROOT / 'ca.pem'),
        '-CAkey', str(ROOT / 'ca.key'), '-set_serial', str(serial), '-days', '3',
        '-extfile', str(ROOT / 'ext.cnf'), '-out', str(directory / 'fullchain.pem'))


run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-noenc', '-days', '3', '-subj', '/CN=tmail test CA',
    '-keyout', str(ROOT / 'ca.key'), '-out', str(ROOT / 'ca.pem'),
    '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
issue_cert(Path('/certificates/current'), 1)
for name in ('admin', 'owner', 'maintenance'):
    Path(f'/run/secrets/{name}_password').write_text(PASSWORDS[name] + '\n')
Path('/run/secrets/blob_key').write_text(base64.b64encode(secrets.token_bytes(32)).decode() + '\n')
os.environ.update(TMAIL_HOSTNAME=HOST, TMAIL_PROXY_IP='127.0.0.2', TMAIL_MAINTENANCE_IP='127.0.0.1',
                  SSL_CERT_FILE=str(ROOT / 'ca.pem'),
                  CURL_CA_BUNDLE=str(ROOT / 'ca.pem'))
TLS = ssl.create_default_context(cafile=str(ROOT / 'ca.pem'))


def start():
    global process
    log = open(ROOT / 'server.log', 'a')
    process = subprocess.Popen(['/opt/tmail/scripts/mail-entrypoint.sh'], stdout=log, stderr=log)
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError(f'server exited {process.returncode}')
        try:
            with socket.create_connection(('127.0.0.1', 1993), timeout=0.3):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError('server start timed out')


def stop():
    process.send_signal(signal.SIGTERM)
    process.wait(timeout=20)


class LocalHTTPS(http.client.HTTPSConnection):
    def connect(self):
        self.sock = TLS.wrap_socket(socket.create_connection(('127.0.0.1', 8444), timeout=10), server_hostname=HOST)


def api(method, arguments, user='admin', expected=True):
    connection = LocalHTTPS(HOST, context=TLS, timeout=10)
    credential = base64.b64encode(f'{user}@tmail.internal:{PASSWORDS[user]}'.encode()).decode()
    body = json.dumps({'using': ['urn:ietf:params:jmap:core'], 'methodCalls': [[method, arguments, 't']]})
    connection.request('POST', '/jmap', body, {'Content-Type': 'application/json', 'Authorization': f'Basic {credential}'})
    response = connection.getresponse()
    data = json.loads(response.read())
    connection.close()
    if not expected:
        return response.status, data
    assert response.status == 200, data
    name, result, _ = data['methodResponses'][0]
    assert name == method, data
    assert not result.get('notCreated') and not result.get('notUpdated') and not result.get('notDestroyed'), data
    return result


def objects(kind):
    ids = api(f'x:{kind}/query', {})['ids']
    return api(f'x:{kind}/get', {'ids': ids})['list'] if ids else []


def create(kind, value):
    return api(f'x:{kind}/set', {'create': {'new': value}})['created']['new']['id']


def action(name, user='admin'):
    return api('x:Action/set', {'create': {'reload': {'@type': name}}}, user)


def smtp(user=None):
    # Verify TLS hostname while connecting to an isolated loopback listener.
    client = smtplib.SMTP_SSL(context=TLS, timeout=8)
    client._host = HOST
    client.connect('127.0.0.1', 1465)
    client.ehlo()
    if user:
        client.login(f'{user}@tmail.internal', PASSWORDS[user])
    return client


def message(sender, to='owner', **headers):
    msg = email.message.EmailMessage()
    msg['From'] = f'{sender}@tmail.internal'
    msg['To'] = f'{to}@tmail.internal'
    msg['Subject'] = 'tmail isolated test'
    msg['Message-ID'] = f'<{secrets.token_hex(8)}@tmail.internal>'
    for key, value in headers.items():
        msg[key.replace('_', '-')] = value
    msg.set_content('private dummy message ' + secrets.token_hex(32))
    return msg.as_bytes()


def send(sender, recipient, content=None):
    with smtp(sender) as client:
        return client.sendmail(f'{sender}@tmail.internal', [f'{recipient}@tmail.internal'],
                               content or message(sender, recipient))


def inbox(user):
    client = imaplib.IMAP4_SSL(host=HOST, port=1993, ssl_context=TLS, timeout=10)
    client.login(f'{user}@tmail.internal', PASSWORDS[user])
    client.select('INBOX')
    status, ids = client.search(None, 'ALL')
    client.logout()
    assert status == 'OK'
    return ids[0].split()


try:
    start()
    check(True, 'empty-volume bootstrap starts TLS listeners without a storage-encryption acknowledgement')
    domains = objects('Domain')
    domain = next(d['id'] for d in domains if d['name'] == 'tmail.internal')
    account_ids = {}
    for name in ('alpha', 'beta'):
        account_ids[name] = create('Account', {'@type': 'User', 'name': name, 'domainId': domain,
            'roles': {'@type': 'User'}, 'credentials': {'0': {'@type': 'Password', 'secret': PASSWORDS[name]}},
            'quotas': {'maxDiskQuota': 1073741824}})
    check(len(objects('NetworkListener')) == 4, 'only four configured TLS listeners (three forwarded, one internal)')
    check(all(x['implicitTls'] for x in objects('NetworkListener')), 'all normal listeners require implicit TLS')
    check([r['@type'] for r in objects('MtaRoute')] == ['Local'], 'only local delivery route exists')
    for port in (25, 143, 587, 8080, 4190):
        try:
            socket.create_connection(('127.0.0.1', port), timeout=1).close()
            raise AssertionError(f'unexpected listener on {port}')
        except ConnectionRefusedError:
            pass
    check(True, 'plaintext, ManageSieve, and recovery ports are closed')
    with socket.create_connection(('127.0.0.1', 1465), timeout=2) as plain:
        plain.sendall(b'EHLO plaintext\r\n')
        try:
            reply = plain.recv(1024)
            check(reply == b'' or reply.startswith(b'\x15'), 'plaintext rejected on TLS port')
        except ConnectionResetError:
            check(True, 'plaintext rejected on TLS port')
    for context, hostname in ((TLS, 'wrong.test.ts.net'), (ssl.create_default_context(cafile='/etc/ssl/certs/ca-certificates.crt'), HOST)):
        try:
            with context.wrap_socket(socket.create_connection(('127.0.0.1', 1465), timeout=2), server_hostname=hostname):
                raise AssertionError('invalid certificate trusted')
        except ssl.SSLCertVerificationError:
            check(True, f'TLS verification rejects {hostname if hostname != HOST else "untrusted issuer"}')
    with smtp() as client:
        check(client.mail('alpha@tmail.internal')[0] == 503, 'unauthenticated submission rejected')
    try:
        with smtp() as client:
            client.login('alpha@tmail.internal', 'invalid-password')
        raise AssertionError('invalid password accepted')
    except smtplib.SMTPAuthenticationError:
        check(True, 'invalid password rejected')
    with smtp('alpha') as client:
        check(client.mail('owner@tmail.internal')[0] >= 500, 'spoofed SMTP envelope rejected')
    for recipient in ('beta@tmail.internal', 'somebody@example.com', 'owner+tag@tmail.internal', 'nobody@tmail.internal'):
        with smtp('alpha') as client:
            client.mail('alpha@tmail.internal')
            check(client.rcpt(recipient)[0] >= 500, f'denied recipient {recipient}')
    check(send('owner', 'alpha') == {}, 'owner can send to an agent')
    check(send('alpha', 'owner') == {}, 'agent can reply to owner')
    for content, label in [
        (message('owner'), 'spoofed From'),
        (b'From: alpha@tmail.internal\r\nFrom: owner@tmail.internal\r\nTo: owner@tmail.internal\r\n\r\nspoof', 'duplicate From'),
        (b'From: alpha@tmail.internal, owner@tmail.internal\r\nTo: owner@tmail.internal\r\n\r\nspoof', 'multiple From addresses'),
        (message('alpha', Reply_To='beta@tmail.internal'), 'spoofed Reply-To'),
        (message('alpha', Sender='owner@tmail.internal'), 'spoofed Sender'),
        (b'To: owner@tmail.internal\r\n\r\nno sender', 'missing From'),
    ]:
        try:
            send('alpha', 'owner', content)
            raise AssertionError(f'{label} accepted')
        except smtplib.SMTPDataError as exc:
            check(exc.smtp_code >= 500, f'{label} rejected at DATA')
    with smtp('alpha') as client:
        client.mail('alpha@tmail.internal')
        check(client.rcpt('owner@tmail.internal')[0] == 250 and client.rcpt('beta@tmail.internal')[0] >= 500,
              'every CC/BCC envelope recipient is checked')
    pair = create('MemoryLookupKey', {'namespace': 'tmail-peers', 'key': 'alpha@tmail.internal|beta@tmail.internal', 'isGlobPattern': False})
    action('ReloadLookupStores')
    check(send('alpha', 'beta') == {}, 'explicit directed peer grant permits delivery')
    with smtp('beta') as client:
        client.mail('beta@tmail.internal')
        check(client.rcpt('alpha@tmail.internal')[0] >= 500, 'peer permission is directional')
    api('x:MemoryLookupKey/set', {'destroy': [pair]})
    action('ReloadLookupStores')
    with smtp('alpha') as client:
        client.mail('alpha@tmail.internal')
        check(client.rcpt('beta@tmail.internal')[0] >= 500, 'peer revocation takes effect after reload')
    status, result = api('x:Account/query', {}, 'alpha', False)
    check(status == 403 or result.get('methodResponses', [['']])[0][0] == 'error', 'agent cannot administer accounts')
    action('ReloadTlsCertificates', 'maintenance')
    check(True, 'restricted maintenance account can reload certificates')
    status, result = api('x:Account/query', {}, 'maintenance', False)
    check(status == 403 or result.get('methodResponses', [['']])[0][0] == 'error', 'maintenance cannot read accounts')
    for _ in range(40):
        if len(inbox('alpha')) == 1 and len(inbox('beta')) == 1:
            break
        time.sleep(0.25)
    check(len(inbox('alpha')) == 1 and len(inbox('beta')) == 1, 'IMAP delivers only each mailbox’s messages')
    with smtp('alpha') as client:
        check(client.mail('alpha@tmail.internal', options=['SIZE=10485761'])[0] >= 500, '10 MiB message limit enforced')
    with smtp('owner') as client:
        client.mail('owner@tmail.internal')
        api('x:Account/set', {'create': {f'limit{i}': {'@type': 'User', 'name': f'limit{i}', 'domainId': domain,
                'roles': {'@type': 'User'}, 'quotas': {'maxDiskQuota': 1073741824}} for i in range(21)}})
        codes = [client.rcpt(f'limit{i}@tmail.internal')[0] for i in range(21)]
        check(codes[-1] >= 400, '20-recipient limit enforced')
    health = run('/opt/tmail/scripts/mail-health.sh')
    check(True, 'health check verifies TLS')
    connection = LocalHTTPS(HOST, context=TLS)
    connection.request('GET', '/admin/')
    response = connection.getresponse()
    check(response.status == 200 and len(response.read()) > 1000, 'bundled WebUI serves without internet')
    connection.close()
    old = PASSWORDS['alpha']
    PASSWORDS['alpha'] = secrets.token_urlsafe(32)
    api('x:Account/set', {'update': {account_ids['alpha']: {'credentials': {'0': {'@type': 'Password', 'secret': PASSWORDS['alpha']}}}}})
    stop()
    start()
    check(len(inbox('alpha')) == 1, 'restart preserves messages and changed credentials')
    check(next(a['id'] for a in objects('Account') if a['name'] == 'alpha') == account_ids['alpha'], 'restart preserves account identities')
    check(objects('MemoryLookupKey') == [], 'restart preserves revoked peer policies')
    # The blob key reference, not the key itself, is retained in the database.
    email_settings = api('x:Email/get', {'ids': ['singleton']})['list'][0]
    check(bool(email_settings['blobEncryptionKey']), 'blob encryption enabled with a separate key object')
    check(next(a['quotas']['maxDiskQuota'] for a in objects('Account') if a['name'] == 'owner') == 1073741824,
          'owner mailbox has the 1 GiB default quota')
    api('x:Account/set', {'update': {account_ids['beta']: {'quotas': {'maxDiskQuota': 4096}}}})
    with imaplib.IMAP4_SSL(host=HOST, port=1993, ssl_context=TLS, timeout=10) as client:
        client.login('beta@tmail.internal', PASSWORDS['beta'])
        status, detail = client.append('INBOX', None, None, message('beta') + b'x' * 8192)
        check(status == 'NO', 'mailbox quota rejects an oversized IMAP append')
    client = imaplib.IMAP4_SSL(host=HOST, port=1993, ssl_context=TLS, timeout=10)
    client.login('beta@tmail.internal', PASSWORDS['beta'])
    try:
        status, detail = client.setacl('INBOX', 'alpha@tmail.internal', 'lrswipkxte')
        check(status == 'NO', 'agent cannot share its mailbox to bypass isolation')
    except imaplib.IMAP4.abort:
        check(True, 'forbidden SETACL disconnects the agent')
    finally:
        client.shutdown()
    # A fresh account makes the submission counter deterministic.
    PASSWORDS['rate'] = secrets.token_urlsafe(32)
    create('Account', {'@type': 'User', 'name': 'rate', 'domainId': domain, 'roles': {'@type': 'User'},
        'credentials': {'0': {'@type': 'Password', 'secret': PASSWORDS['rate']}}, 'quotas': {'maxDiskQuota': 1073741824}})
    with smtp('rate') as client:
        codes = []
        for _ in range(61):
            client.rset()
            codes.append(client.mail('rate@tmail.internal')[0])
        check(all(c == 250 for c in codes[:60]) and codes[60] >= 400, '60 submissions per minute per account enforced')
    # Check PROXY v2 preserves the authenticated node IP for credential policies.
    api('x:Account/set', {'update': {account_ids['alpha']: {'credentials': {'0': {'@type': 'Password',
        'secret': PASSWORDS['alpha'], 'allowedIps': {'100.64.0.40/32': True}}}}}})
    raw = socket.socket()
    raw.settimeout(5)
    raw.bind(('127.0.0.2', 0))
    raw.connect(('127.0.0.1', 1465))
    raw.sendall(b'\r\n\r\n\x00\r\nQUIT\n' + bytes([0x21, 0x11]) + struct.pack('!H', 12)
                + socket.inet_aton('100.64.0.40') + socket.inet_aton('100.64.0.50') + struct.pack('!HH', 12345, 465))
    with smtplib.SMTP_SSL(context=TLS, timeout=5) as client:
        client.sock = TLS.wrap_socket(raw, server_hostname=HOST)
        check(client.getreply()[0] == 220, 'PROXY v2 accepted from the configured proxy')
        client.ehlo()
        check(client.login('alpha@tmail.internal', PASSWORDS['alpha'])[0] == 235, 'forwarded node IP reaches credential access control')
    try:
        with smtp('alpha'):
            raise AssertionError('direct connection bypassed IP restriction')
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPServerDisconnected):
        check(True, 'direct backend connection cannot claim a forwarded identity')
    api('x:Account/set', {'update': {account_ids['alpha']: {'credentials': {'0': {'@type': 'Password', 'secret': PASSWORDS['alpha']}}}}})
    issue_cert(Path('/certificates/next'), 2)
    old_cert = TLS.wrap_socket(socket.create_connection(('127.0.0.1', 1465)), server_hostname=HOST)
    first_serial = old_cert.getpeercert()['serialNumber']
    old_cert.close()
    shutil.rmtree('/certificates/current')
    Path('/certificates/current').symlink_to('next')
    action('ReloadTlsCertificates', 'maintenance')
    with TLS.wrap_socket(socket.create_connection(('127.0.0.1', 1465)), server_hostname=HOST) as renewed:
        check(renewed.getpeercert()['serialNumber'] != first_serial, 'certificate reload replaces the live TLS certificate')
    stop()
    # A cold copy is the restore procedure. The encryption key is kept separately.
    shutil.copytree('/var/lib/stalwart', ROOT / 'backup')
    for item in Path('/var/lib/stalwart').iterdir():
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    shutil.copytree(ROOT / 'backup', '/var/lib/stalwart', dirs_exist_ok=True)
    start()
    check(len(inbox('alpha')) == 1, 'cold backup restore preserves decryptable mail and credentials')
    if shutil.which('himalaya'):
        from mcp import exercise_mcp
        exercise_mcp(ROOT, HOST, PASSWORDS['alpha'], check)
        for _ in range(40):
            if len(inbox('owner')) == 3:
                break
            time.sleep(0.25)
        check(len(inbox('owner')) == 3, 'MCP new message and reply arrive in the owner mailbox')
        with imaplib.IMAP4_SSL(host=HOST, port=1993, ssl_context=TLS, timeout=10) as client:
            client.login('alpha@tmail.internal', PASSWORDS['alpha'])
            client.select('INBOX')
            original = email.message_from_bytes(client.fetch('1', '(RFC822)')[1][0][1])
        with imaplib.IMAP4_SSL(host=HOST, port=1993, ssl_context=TLS, timeout=10) as client:
            client.login('owner@tmail.internal', PASSWORDS['owner'])
            client.select('INBOX')
            replies = [email.message_from_bytes(item[1]) for item in client.fetch('1:*', '(RFC822)')[1] if isinstance(item, tuple)]
        check(any(original['Message-ID'] in str(reply.get('In-Reply-To', '')) and
                  original['Message-ID'] in str(reply.get('References', '')) for reply in replies),
              'delivered MCP reply preserves In-Reply-To and References threading')
    print(f'\n{checks} checks passed', flush=True)
finally:
    if process and process.poll() is None:
        stop()
    for path in (ROOT / 'server.log', Path('/run/tmail/recovery.log')):
        if path.exists():
            print(f'--- {path} ---\n{path.read_text()[-10000:]}', flush=True)
