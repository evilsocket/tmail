#!/bin/sh
set -eu
umask 077
: "${TMAIL_HOSTNAME:?}" "${TS_SOCKET:?}"
mkdir -p /certificates
trap 'exit 0' TERM INT
while :; do
  if /opt/tmail/scripts/renew-certificate.sh; then
    sleep 43200 & wait $! || :
  else
    echo 'Certificate maintenance failed; retaining the last certificate and retrying in 5 minutes.' >&2
    sleep 300 & wait $! || :
  fi
done
