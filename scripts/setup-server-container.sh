#!/bin/sh
# Invoked in the tools image, never directly on the host.
set -eu
cd /workspace
umask 077
hostname=${1:?Usage: ./scripts/setup.sh tmail.YOUR-TAILNET.ts.net}
printf '%s' "$hostname" | grep -Eq '^tmail\.[a-z0-9.-]+\.ts\.net$' || {
  echo 'Expected the dedicated node FQDN: tmail.<tailnet>.ts.net' >&2; exit 1;
}
mkdir -p .secrets
chmod 700 .secrets
for name in admin_password owner_password maintenance_password blob_key; do
  if [ ! -e ".secrets/$name" ]; then
    openssl rand -base64 32 > ".secrets/$name"
    # The directory is 0700; bind-mounted files must be readable by UID 2000.
    chmod 444 ".secrets/$name"
  fi
done
if [ ! -e .secrets/tailscale_authkey ]; then
  : > .secrets/tailscale_authkey
  chmod 644 .secrets/tailscale_authkey
fi
if [ ! -e .env ]; then
  sed "s/tmail.YOUR-TAILNET.ts.net/$hostname/" /opt/tmail/server.env.example > .env
fi
echo 'Prepared .env and .secrets without replacing existing values.'
echo 'Follow README.md: enable Tailscale HTTPS certificates, add the auth key, then run docker compose up -d --build.'
