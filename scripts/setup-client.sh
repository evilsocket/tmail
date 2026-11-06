#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
[ "$#" -ge 2 ] || {
  echo 'Usage: scripts/setup-client.sh tmail.YOUR-TAILNET.ts.net MAILBOX [CLIENT-NAME]' >&2
  exit 1
}
docker build --target tools -t tmail-tools:local . >&2
exec docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" --tmpfs /tmp \
  --mount "type=bind,src=$PWD,dst=/workspace" \
  tmail-tools:local /opt/tmail/scripts/setup-client-container.sh "$@"
