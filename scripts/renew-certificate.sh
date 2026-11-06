#!/bin/sh
set -eu
umask 077
stage=$(mktemp -d /certificates/.pending.XXXXXX)
trap 'rm -rf "$stage"' EXIT
tailscale --socket="$TS_SOCKET" cert --cert-file="$stage/fullchain.pem" \
  --key-file="$stage/privkey.pem" "$TMAIL_HOSTNAME" >/dev/null
openssl x509 -in "$stage/fullchain.pem" -noout -checkhost "$TMAIL_HOSTNAME" >/dev/null
openssl x509 -in "$stage/fullchain.pem" -noout -checkend 86400 >/dev/null
openssl verify -CAfile "${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" \
  -untrusted "$stage/fullchain.pem" "$stage/fullchain.pem" >/dev/null
openssl x509 -in "$stage/fullchain.pem" -pubkey -noout > "$stage/cert.pub"
openssl pkey -in "$stage/privkey.pem" -pubout > "$stage/key.pub"
cmp -s "$stage/cert.pub" "$stage/key.pub"
rm "$stage/cert.pub" "$stage/key.pub"
chown -R 0:2000 "$stage"
chmod 750 "$stage"
chmod 640 "$stage/fullchain.pem" "$stage/privkey.pem"
fingerprint=$(sha256sum "$stage/fullchain.pem" | cut -d ' ' -f 1)
generation="generation-$fingerprint"
if [ ! -d "/certificates/$generation" ]; then mv "$stage" "/certificates/$generation"; fi
rm -f /certificates/.current-next
ln -s "$generation" /certificates/.current-next
mv -Tf /certificates/.current-next /certificates/current
# Retry reload even when the certificate hasn't changed: a previous reload may
# have failed while mail was bootstrapping. If the served certificate has already
# expired, mail's local watchdog restarts it with this validated replacement.
# Keep old generations for recovery; never bypass verification of the reload API.
password=$(cat /run/secrets/maintenance_password)
credential=$(printf 'maintenance@tmail.internal:%s' "$password" | base64 -w 0)
printf 'header = "Authorization: Basic %s"\n' "$credential" > /run/tmail/curl-auth
unset password credential
trap 'rm -rf "$stage"; rm -f /run/tmail/curl-auth /run/tmail/reload.json' EXIT
curl --silent --show-error --fail --max-time 20 --config /run/tmail/curl-auth \
  -H 'Content-Type: application/json' --data-binary @/opt/tmail/config/reload-certificates.json \
  "https://$TMAIL_HOSTNAME:8444/jmap" > /run/tmail/reload.json
jq -e '.methodResponses[0][0] == "x:Action/set" and .methodResponses[0][1].created.reload != null' \
  /run/tmail/reload.json >/dev/null
echo 'Certificate validated and TLS certificate reload completed.'
