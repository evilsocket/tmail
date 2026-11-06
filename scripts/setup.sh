#!/bin/sh
# Docker is the only installed dependency; the host uses ordinary POSIX utilities.
set -eu
cd "$(dirname "$0")/.."
hostname=${1:?Usage: ./scripts/setup.sh tmail.YOUR-TAILNET.ts.net}
docker build --target tools -t tmail-tools:local . >&2
exec docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --user "$(id -u):$(id -g)" --tmpfs /tmp \
  --mount "type=bind,src=$PWD,dst=/workspace" \
  tmail-tools:local /opt/tmail/scripts/setup-server-container.sh "$hostname"
