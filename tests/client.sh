#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
for target in tools client client-gateway test test-client-driver; do
  docker build --target "$target" -t "tmail-$target:local" .
done
work=$(mktemp -d "${TMPDIR:-/tmp}/tmail-client-tests.XXXXXX")
# Only this synthetic directory is writable. Never mount the checkout's secrets.
trap 'docker run --rm --network none --mount "type=bind,src=$work,dst=/workspace" tmail-tools:local sh -c "rm -rf /workspace/* /workspace/.[!.]*"; rmdir "$work"' EXIT
docker run --rm --network none \
  --mount type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock \
  --mount "type=bind,src=$PWD/tests,dst=/tests,readonly" \
  --mount "type=bind,src=$PWD/compose.client.yaml,dst=/compose.client.yaml,readonly" \
  --mount "type=bind,src=$work,dst=/workspace" \
  --mount "type=bind,src=$work,dst=$work" \
  -e "TMAIL_TEST_HOST_WORK=$work" -e "TMAIL_TEST_HOST_REPO=$PWD" \
  tmail-test-client-driver:local
