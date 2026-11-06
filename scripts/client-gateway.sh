#!/bin/sh
set -eu
printf '%s' "$TMAIL_HOSTNAME" | grep -Eq '^tmail\.[a-z0-9.-]+\.ts\.net$'
TS_AUTHKEY=$(cat /run/secrets/tailscale_authkey)
export TS_AUTHKEY
/usr/local/bin/containerboot &
daemon=$!
unset TS_AUTHKEY
imap= smtp= timer=
cleanup() {
  for child in "$daemon" "$imap" "$smtp" "$timer"; do
    [ -z "$child" ] || kill "$child" 2>/dev/null || :
  done
  wait 2>/dev/null || :
}
trap cleanup EXIT
trap 'exit 0' INT TERM
# Bind only the internal Docker network's alias; never publish these ports.
bind=${TMAIL_GATEWAY_BIND:-tmail-client-backend}
socat "TCP4-LISTEN:1993,bind=$bind,reuseaddr,fork,max-children=32" \
  'EXEC:/opt/tmail/client-connect.sh 993' &
imap=$!
socat "TCP4-LISTEN:1465,bind=$bind,reuseaddr,fork,max-children=32" \
  'EXEC:/opt/tmail/client-connect.sh 465' &
smtp=$!
while kill -0 "$daemon" && kill -0 "$imap" && kill -0 "$smtp"; do
  sleep 1 & timer=$!
  wait "$timer" || :
  timer=
done
echo 'Client gateway stopped; restarting through the container policy.' >&2
exit 1
