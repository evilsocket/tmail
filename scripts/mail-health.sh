#!/bin/sh
set -eu
[ -f /run/tmail/ready ]
/opt/tmail/scripts/cert-health.sh >/dev/null
curl --silent --fail --max-time 4 --resolve "$TMAIL_HOSTNAME:8444:127.0.0.1" \
  "https://$TMAIL_HOSTNAME:8444/healthz/live" >/dev/null
