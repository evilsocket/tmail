#!/bin/sh
set -eu
umask 077
cd /workspace
hostname=${1:?Server hostname required}
mailbox=${2:?User-selected mailbox local part required}
name=${3:-$mailbox}
printf '%s' "$hostname" | grep -Eq '^tmail\.[a-z0-9.-]+\.ts\.net$'
printf '%s' "$mailbox" | grep -Eq '^[a-z0-9][a-z0-9._-]{0,63}$'
case "$mailbox" in admin|owner|maintenance) echo 'Use an ordinary agent mailbox.' >&2; exit 1;; esac
printf '%s' "$name" | grep -Eq '^[a-z0-9][a-z0-9-]{0,40}$' || {
  echo 'Supply a client name with lowercase letters, digits, and hyphens (max 41 characters).' >&2
  exit 1
}
directory=".clients/$name"
mkdir -p "$directory/mail" "$directory/state"
chmod 700 .clients "$directory" "$directory/mail" "$directory/state"
if [ -f "$directory/client.env" ]; then
  # Preserve passwords, allowlists, cursor state, and intentional local settings.
  grep -qxF "TMAIL_HOSTNAME=$hostname" "$directory/client.env"
  grep -qxF "TMAIL_MAILBOX=$mailbox" "$directory/client.env"
  echo "Existing client $name preserved. Follow docs/clients.md to resume setup."
  exit 0
fi
# Refuse to replace partially prepared configuration; let the operator recover it.
for file in mail/himalaya.toml mail/channel.json mail/password tailscale_authkey; do
  [ ! -e "$directory/$file" ] || { echo "Existing client files need inspection: $directory" >&2; exit 1; }
done
cat > "$directory/mail/himalaya.toml" <<EOF
[accounts.tmail]
default = true
email = "$mailbox@tmail.internal"
imap.server = "imaps://$hostname:1993"
imap.sasl.plain.username = "$mailbox@tmail.internal"
imap.sasl.plain.password.command = "cat /config/password"
smtp.server = "smtps://$hostname:1465"
smtp.sasl.plain.username = "$mailbox@tmail.internal"
smtp.sasl.plain.password.command = "cat /config/password"
EOF
jq -n --arg host "$hostname" --arg user "$mailbox@tmail.internal" \
  '{host:$host,port:1993,username:$user,passwordFile:"/config/password",
    allowedSenders:["owner@tmail.internal"],stateDirectory:"/state/inbox"}' \
  > "$directory/mail/channel.json"
: > "$directory/mail/password"
: > "$directory/tailscale_authkey"
chmod 644 "$directory/tailscale_authkey"
cat > "$directory/client.env" <<EOF
TMAIL_HOSTNAME=$hostname
TMAIL_MAILBOX=$mailbox
TMAIL_CLIENT_NAME=$name
TMAIL_CLIENT_UID=$(id -u)
TMAIL_CLIENT_GID=$(id -g)
EOF
echo "Prepared $directory without creating a server mailbox."
echo 'Fill mail/password with that mailbox password and tailscale_authkey with a new enrollment key.'
echo 'See docs/clients.md to build, start the gateway, and register the Docker MCP commands.'
