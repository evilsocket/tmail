"""Execute the documented backup recipe with isolated command stubs, never Docker."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

document = (Path(__file__).resolve().parent.parent / 'docs/operations.md').read_text()
section = document.split('## Encrypted cold backup\n', 1)[1]
recipe = re.search(r'```bash\n(.*?)\n```', section, re.S).group(1)
stub = r'''
import os
from pathlib import Path
import signal
import sys

command = Path(sys.argv[0]).name
args = sys.argv[1:]
failure = os.environ['TEST_FAILURE']
with open(os.environ['TEST_EVENTS'], 'a') as log:
    log.write(command + ' ' + ' '.join(args) + '\n')
if command == 'docker' and args[0] == 'run':
    image = args.index('tmail-tools:local')
    command, args = args[image + 1], args[image + 2:]
if command == 'docker':
    if args == ['compose', 'stop']:
        if failure in ('HUP', 'INT', 'TERM'):
            os.kill(os.getppid(), getattr(signal, 'SIG' + failure))
        if failure == 'write':
            next(Path('backups').iterdir()).joinpath('mail.tar.age').mkdir()
        sys.exit(31 if failure == 'stop' else 0)
    if args == ['compose', 'up', '-d']:
        sys.exit(46 if os.environ.get('TEST_RESUME_FAIL') == '1' else 0)
    if 'mail' in args and failure == 'mail':
        sys.exit(41)
    if 'tailscale' in args and failure == 'tailscale':
        sys.exit(42)
elif command == 'tar':
    if '.env' in args and failure == 'deployment':
        sys.exit(43)
    if '.secrets' in args and failure == 'secrets':
        sys.exit(44)
elif command == 'age':
    sys.stdin.buffer.read()
    if failure == 'encryption':
        sys.exit(45)
print('synthetic archive')
'''

cases = [('success', 0), ('stop', 31), ('mail', 41), ('tailscale', 42),
         ('deployment', 43), ('secrets', 44), ('encryption', 45), ('write', 1),
         ('HUP', 129), ('INT', 130), ('TERM', 143), ('resume', 46), ('mail+resume', 41)]
for failure, expected in cases:
    with tempfile.TemporaryDirectory(prefix='tmail-backup-') as directory:
        root = Path(directory)
        commands = root / 'bin'
        commands.mkdir()
        for name in ('docker', 'tar', 'age'):
            path = commands / name
            path.write_text(f'#!{sys.executable}\n' + stub)
            path.chmod(0o700)
        events = root / 'events'
        env = dict(os.environ, PATH=f'{commands}:{os.environ["PATH"]}',
                   TEST_EVENTS=str(events), TEST_FAILURE=failure.split('+')[0],
                   TEST_RESUME_FAIL='1' if 'resume' in failure else '0')
        result = subprocess.run(['bash', '-c', recipe], cwd=root, env=env,
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == expected, (failure, result.returncode, result.stderr)
        calls = events.read_text().splitlines()
        assert calls[0].startswith('docker build --target tools'), (failure, calls)
        assert calls[1] == 'docker compose stop', (failure, calls)
        assert calls[-1] == 'docker compose up -d', (failure, calls)
        assert calls.count('docker compose up -d') == 1, (failure, calls)
        if failure == 'success':
            assert len(list(root.glob('backups/*/*.age'))) == 4
        print(f'PASS backup {failure}: resumes once and preserves exit status', flush=True)
print(f'{len(cases)} backup cleanup checks passed')
