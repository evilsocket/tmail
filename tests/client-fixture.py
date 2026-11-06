"""Synthetic mail server for the production client-container tests."""
from pathlib import Path
exec(Path('/tests/integration.py').read_text().split('\ntry:\n    start()\n')[0], globals())

shared = Path('/shared')
try:
    start()
    domain = next(d['id'] for d in objects('Domain') if d['name'] == 'tmail.internal')
    create('Account', {'@type': 'User', 'name': 'alpha', 'domainId': domain,
                      'roles': {'@type': 'User'},
                      'credentials': {'0': {'@type': 'Password', 'secret': PASSWORDS['alpha']}},
                      'quotas': {'maxDiskQuota': 1073741824}})
    (shared / 'password').write_text(PASSWORDS['alpha'])
    shutil.copy(ROOT / 'ca.pem', shared / 'ca.pem')
    send('owner', 'alpha')
    for _ in range(50):
        if len(inbox('alpha')) == 1:
            break
        time.sleep(.1)
    (shared / 'ready').touch()
    while True:
        request = shared / 'deliver'
        if request.exists():
            send('owner', 'alpha')
            request.unlink()
            (shared / 'delivered').touch()
        time.sleep(.1)
finally:
    if process and process.poll() is None:
        stop()
