#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker build --target test-channel -t tmail-test-channel:local .
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp --workdir /channel --entrypoint node tmail-test-channel:local --test test/channel.test.mjs
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 2g --cpus 2 --pids-limit 128 \
  --add-host tmail.test.ts.net:127.0.0.1 --add-host tmail.wrong.ts.net:127.0.0.1 \
  --tmpfs /var/lib/stalwart:uid=2000,gid=2000 --tmpfs /etc/stalwart:uid=2000,gid=2000 \
  --tmpfs /certificates:uid=2000,gid=2000 --tmpfs /run/secrets:uid=2000,gid=2000 \
  --tmpfs /tmp:uid=2000,gid=2000 --tmpfs /run/tmail:uid=2000,gid=2000 \
  --tmpfs /var/cache/tmail:uid=2000,gid=2000 -v "$PWD/tests:/tests:ro" tmail-test-channel:local
