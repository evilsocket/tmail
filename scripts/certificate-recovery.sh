#!/bin/sh
# Run beside Stalwart with the same unprivileged UID; no credentials or Docker socket.
set -eu
server_pid=${1:?Stalwart PID required}
case "$server_pid" in ''|*[!0-9]*|0|1) exit 1;; esac
interval=${TMAIL_CERT_CHECK_INTERVAL:-30}
case "$interval" in ''|*[!0-9]*|0) exit 1;; esac
sleep_pid=
cleanup() {
  if [ -n "$sleep_pid" ]; then
    kill "$sleep_pid" 2>/dev/null || :
    wait "$sleep_pid" 2>/dev/null || :
  fi
}
trap cleanup EXIT
trap 'exit 0' INT TERM
while kill -0 "$server_pid" 2>/dev/null; do
  sleep "$interval" &
  sleep_pid=$!
  wait "$sleep_pid" || :
  sleep_pid=
  kill -0 "$server_pid" 2>/dev/null || exit 0
  # Missing/invalid replacements must never cause a restart or a TLS bypass.
  /opt/tmail/scripts/cert-health.sh >/dev/null 2>&1 || continue
  result=0
  curl --silent --fail --max-time 4 --noproxy '*' --proto '=https' \
    --cacert "${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" \
    --resolve "$TMAIL_HOSTNAME:8444:127.0.0.1" \
    "https://$TMAIL_HOSTNAME:8444/healthz/live" >/dev/null 2>&1 || result=$?
  if [ "$result" -eq 60 ]; then
    # The loaded certificate cannot authenticate HTTPS, but its on-disk
    # replacement passed all checks. Compose's restart policy reruns the normal
    # bootstrap to load it, including recreating a removed Certificate object.
    echo 'Served TLS certificate failed verification; restarting mail with a validated replacement.' >&2
    kill -TERM "$server_pid" 2>/dev/null || :
    exit 0
  fi
done
