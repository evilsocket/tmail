#!/bin/sh
set -eu
umask 077
case "${TMAIL_HOSTNAME:-}" in
  tmail.*.ts.net) ;; *) echo 'TMAIL_HOSTNAME must be the exact tmail.*.ts.net node name.' >&2; exit 1;;
esac
printf '%s' "$TMAIL_HOSTNAME" | grep -Eq '^tmail\.[a-z0-9.-]+\.ts\.net$' || exit 1
rm -f /run/tmail/ready
echo 'Waiting for a valid tailnet certificate.'
until /opt/tmail/scripts/cert-health.sh >/dev/null 2>&1; do sleep 5; done
printf '%s\n' '{"@type":"RocksDb","path":"/var/lib/stalwart/"}' > /etc/stalwart/config.json

# Recovery only exposes port 8080 on the isolated backend, never through Serve.
export STALWART_RECOVERY_MODE=1
export STALWART_USER=recovery
STALWART_PASSWORD=$(openssl rand -hex 32)
export STALWART_PASSWORD
export STALWART_RECOVERY_ADMIN="recovery:$STALWART_PASSWORD"
export STALWART_URL=http://127.0.0.1:8080
unset STALWART_PUBLIC_URL
/usr/local/bin/stalwart --config /etc/stalwart/config.json > /run/tmail/recovery.log 2>&1 &
recovery_pid=$!
cleanup() {
  kill "$recovery_pid" 2>/dev/null || :
  wait "$recovery_pid" 2>/dev/null || :
  rm -f /run/tmail/*.ndjson /run/tmail/recovery.log
}
trap cleanup EXIT
trap 'exit 1' INT TERM
attempt=0
until stalwart-cli query Domain --json > /run/tmail/domains.json 2>/dev/null; do
  kill -0 "$recovery_pid" 2>/dev/null || { echo 'Recovery server failed.' >&2; exit 1; }
  attempt=$((attempt + 1))
  [ "$attempt" -lt 60 ] || { echo 'Recovery server timed out.' >&2; exit 1; }
  sleep 1
done

jq -nc --arg hostname "$TMAIL_HOSTNAME" --arg proxy "$TMAIL_PROXY_IP" \
  --slurpfile mailPermissions /opt/tmail/config/mail-permissions.json \
  --slurpfile adminPermissions /opt/tmail/config/admin-permissions.json \
  --rawfile fromScript /opt/tmail/config/check-from.sieve \
  -f /opt/tmail/config/policy.jq > /run/tmail/policy.ndjson
stalwart-cli apply --file /run/tmail/policy.ndjson --json > /run/tmail/apply.log

# 1.0.3 does not resolve JMAP creation references for blobEncryptionKey.
key_id=$(stalwart-cli query SymmetricKey --json | jq -r 'select(.description=="tmail blob encryption") | .id')
domain_id=$(stalwart-cli query Domain --json | jq -r 'select(.name=="tmail.internal") | .id')
maintenance_role=$(stalwart-cli query Role --json | jq -r 'select(.description=="tmail certificate reload") | .id')
[ -n "$key_id" ] && [ -n "$domain_id" ] && [ -n "$maintenance_role" ]
jq -nc --arg key "$key_id" '{"@type":"update",object:"Email",value:{blobEncryptionKey:$key,
  maxMessageSize:10485760,maxAttachmentSize:10485760,maxIdentities:1}}' > /run/tmail/finalize.ndjson
stalwart-cli apply --file /run/tmail/finalize.ndjson --json >> /run/tmail/apply.log

# Query before creating: a restart must never reset a changed password.
stalwart-cli query Account --fields id,name,domainId --json > /run/tmail/accounts.json
for name in admin owner maintenance; do
  if jq -se --arg name "$name" --arg domain "$domain_id" \
    'any(.[]; .name==$name and .domainId==$domain)' /run/tmail/accounts.json >/dev/null; then
    continue
  fi
  jq -nc --arg name "$name" --arg domain "$domain_id" --arg role "$maintenance_role" \
    --arg ip "$TMAIL_MAINTENANCE_IP" --rawfile password "/run/secrets/${name}_password" '
    {"@type":"create",object:"Account",value:{account:{"@type":"User",name:$name,domainId:$domain,
      roles:(if $name=="admin" then {"@type":"Admin"} elif $name=="maintenance" then
        {"@type":"Custom",roleIds:{($role):true}} else {"@type":"User"} end),
      permissions:{"@type":"Inherit"},aliases:{},memberGroupIds:{},quotas:{maxDiskQuota:1073741824},
      credentials:{"0":{"@type":"Password",secret:($password|rtrimstr("\n")),
        allowedIps:(if $name=="maintenance" then {($ip+"/32"):true} else {} end)}}}}}' \
    > /run/tmail/account.ndjson
  stalwart-cli apply --file /run/tmail/account.ndjson --json >> /run/tmail/apply.log
  rm -f /run/tmail/account.ndjson
done
cleanup
trap - EXIT INT TERM
rm -f /run/tmail/*.json /run/tmail/apply.log
unset STALWART_RECOVERY_MODE STALWART_RECOVERY_ADMIN STALWART_PASSWORD STALWART_USER STALWART_URL
export STALWART_PUBLIC_URL="https://$TMAIL_HOSTNAME"
touch /run/tmail/ready
echo 'tmail policies applied; starting TLS listeners.'
/usr/local/bin/stalwart --config /etc/stalwart/config.json &
server_pid=$!
/opt/tmail/scripts/certificate-recovery.sh "$server_pid" &
watcher_pid=$!
runtime_cleanup() {
  kill "$watcher_pid" 2>/dev/null || :
  if [ -n "$server_pid" ]; then kill "$server_pid" 2>/dev/null || :; fi
  wait "$watcher_pid" 2>/dev/null || :
  if [ -n "$server_pid" ]; then wait "$server_pid" 2>/dev/null || :; fi
}
trap runtime_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
result=0
wait "$server_pid" || result=$?
server_pid=
exit "$result"
