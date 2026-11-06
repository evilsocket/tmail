"""Real expired-listener recovery; fresh network-none test container only."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Reuse the synthetic CA, isolated storage, and protocol helpers without running
# the normal suite. Each script gets its own fresh container and tmpfs volumes.
exec(Path('/tests/integration.py').read_text().split('\ntry:\n    start()\n')[0], globals())
os.environ['TMAIL_CERT_CHECK_INTERVAL'] = '1'


def publish(name):
    temporary = Path('/certificates/.test-next')
    temporary.symlink_to(name)
    temporary.replace('/certificates/current')


def curl_health():
    return subprocess.run([
        'curl', '--silent', '--fail', '--max-time', '3', '--noproxy', '*',
        '--cacert', str(ROOT / 'ca.pem'), '--resolve', f'{HOST}:8444:127.0.0.1',
        f'https://{HOST}:8444/healthz/live',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


try:
    Path('/certificates/current').rename('/certificates/initial')
    publish('initial')
    start()
    original_accounts = {account['name']: account['id'] for account in objects('Account')}
    issue_cert(Path('/certificates/replacement'), 3)

    short = Path('/certificates/short')
    short.mkdir()
    run('openssl', 'req', '-new', '-newkey', 'rsa:2048', '-noenc', '-subj', f'/CN={HOST}',
        '-keyout', str(short / 'privkey.pem'), '-out', str(ROOT / 'short.csr'))
    (ROOT / 'index').touch()
    (ROOT / 'serial').write_text('02\n')
    (ROOT / 'ca.cnf').write_text(f'''[ca]
default_ca = local
[local]
database = {ROOT}/index
serial = {ROOT}/serial
new_certs_dir = {ROOT}
certificate = {ROOT}/ca.pem
private_key = {ROOT}/ca.key
default_md = sha256
policy = names
x509_extensions = leaf
[names]
commonName = supplied
[leaf]
subjectAltName = DNS:{HOST}
extendedKeyUsage = serverAuth
basicConstraints = CA:FALSE
''')
    expires = datetime.now(timezone.utc) + timedelta(seconds=8)
    run('openssl', 'ca', '-batch', '-notext', '-config', str(ROOT / 'ca.cnf'),
        '-in', str(ROOT / 'short.csr'), '-out', str(short / 'fullchain.pem'),
        '-startdate', (expires - timedelta(minutes=1)).strftime('%y%m%d%H%M%SZ'),
        '-enddate', expires.strftime('%y%m%d%H%M%SZ'))
    publish('short')
    action('ReloadTlsCertificates', 'maintenance')
    check(curl_health() == 0, 'short-lived loaded certificate initially verifies')
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and curl_health() != 60:
        time.sleep(0.2)
    check(curl_health() == 60, 'expired served certificate fails real TLS verification')
    time.sleep(2)
    check(process.poll() is None, 'expired on-disk certificate does not trigger a restart')

    bad = Path('/certificates/mismatched')
    bad.mkdir()
    shutil.copy('/certificates/replacement/fullchain.pem', bad / 'fullchain.pem')
    shutil.copy(short / 'privkey.pem', bad / 'privkey.pem')
    publish('mismatched')
    time.sleep(2)
    check(process.poll() is None, 'mismatched replacement key does not trigger a restart')

    commands = ROOT / 'bin'
    commands.mkdir()
    (commands / 'tailscale').write_text('''#!/bin/sh
set -eu
for argument do
  case "$argument" in
    --cert-file=*) cp /certificates/replacement/fullchain.pem "${argument#*=}" ;;
    --key-file=*) cp /certificates/replacement/privkey.pem "${argument#*=}" ;;
  esac
done
''')
    # This integration container runs as the mail UID with no capabilities.
    # The existing root/CHOWN lifecycle test exercises real ownership changes.
    (commands / 'chown').write_text('#!/bin/sh\nexit 0\n')
    for command in commands.iterdir():
        command.chmod(0o700)
    renewal_env = dict(os.environ, PATH=f'{commands}:{os.environ["PATH"]}', TS_SOCKET='/test/socket')
    renewal = subprocess.run(['/opt/tmail/scripts/renew-certificate.sh'], env=renewal_env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    check(subprocess.run(['/opt/tmail/scripts/cert-health.sh'], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL).returncode == 0,
          'maintenance installs a valid replacement despite the expired listener')
    check(renewal.returncode != 0, 'renewal installs valid files but expired HTTPS reload still fails')
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        validation = subprocess.run(['/opt/tmail/scripts/cert-health.sh'], capture_output=True, text=True)
        print(f'Replacement validation: {validation.returncode}; HTTPS probe: {curl_health()}', flush=True)
        print(validation.stderr, flush=True)
        print((ROOT / 'server.log').read_text(), flush=True)
        raise
    check('restarting mail with a validated replacement' in (ROOT / 'server.log').read_text(),
          'watchdog terminates mail after validating the replacement')
    check(not Path('/run/tmail/curl-auth').exists(), 'failed reload removes temporary credential material')

    # Emulate Compose unless-stopped after the entrypoint exits, preserving data.
    start()
    check(curl_health() == 0, 'normal bootstrap restores verified HTTPS with the replacement')
    check({account['name']: account['id'] for account in objects('Account')} == original_accounts,
          'certificate recovery preserves accounts and administrator credentials')
    renewal = subprocess.run(['/opt/tmail/scripts/renew-certificate.sh'], env=renewal_env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    check(renewal.returncode == 0, 'restricted HTTPS certificate reload succeeds after recovery')
    time.sleep(2)
    check(process.poll() is None, 'healthy served certificate does not trigger a restart')
    print(f'{checks} certificate recovery checks passed', flush=True)
finally:
    if process is not None and process.poll() is None:
        stop()
