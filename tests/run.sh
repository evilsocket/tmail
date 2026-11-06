#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
target=test
[ "${TMAIL_TEST_MCP:-0}" != 1 ] || target=test-mcp
docker build --target "$target" -t "tmail-$target:local" .
for suite in integration.py certificate-recovery.py; do
  temporary_options=uid=2000,gid=2000
  # Certificate recovery uses temporary synthetic issuance command stubs.
  [ "$suite" != certificate-recovery.py ] || temporary_options="$temporary_options,exec"
  docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
    --memory 2g --cpus 2 --pids-limit 128 --add-host tmail.test.ts.net:127.0.0.1 \
    --tmpfs /var/lib/stalwart:uid=2000,gid=2000 --tmpfs /etc/stalwart:uid=2000,gid=2000 \
    --tmpfs /certificates:uid=2000,gid=2000 --tmpfs /run/secrets:uid=2000,gid=2000 \
    --tmpfs "/tmp:$temporary_options" --tmpfs /run/tmail:uid=2000,gid=2000 \
    --tmpfs /var/cache/tmail:uid=2000,gid=2000 -v "$PWD/tests:/tests:ro" \
    --entrypoint python3 "tmail-$target:local" "/tests/$suite"
done

docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 256m --cpus 1 --pids-limit 64 --tmpfs /tmp:exec,uid=2000,gid=2000 \
  -v "$PWD/tests:/tests:ro" -v "$PWD/docs:/docs:ro" \
  --entrypoint python3 "tmail-$target:local" /tests/backup.py

docker run --rm --network none --read-only --cap-drop ALL --cap-add CHOWN \
  --security-opt no-new-privileges --memory 256m --cpus 1 --pids-limit 64 --user 0:0 \
  --tmpfs /tmp:exec --tmpfs /certificates --tmpfs /run/tmail --tmpfs /run/secrets \
  -v "$PWD/tests:/tests:ro" --entrypoint sh "tmail-$target:local" /tests/certificates.sh

test_network="tmail-test-$$"
docker network create --internal "$test_network" >/dev/null
trap 'docker network rm "$test_network" >/dev/null' EXIT
docker run --rm --network "$test_network" --read-only --cap-drop ALL \
  --security-opt no-new-privileges --memory 256m --cpus 1 --pids-limit 64 \
  -v "$PWD/config/resolv.conf:/etc/resolv.conf:ro" -v "$PWD/tests:/tests:ro" \
  --entrypoint python3 "tmail-$target:local" /tests/network.py
