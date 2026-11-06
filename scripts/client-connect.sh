#!/bin/sh
set -eu
case "${1:-}" in 465|993) ;; *) exit 1;; esac
# The destination is fixed by deployment configuration, never by a connecting client.
exec tailscale --socket="$TS_SOCKET" nc "$TMAIL_HOSTNAME" "$1"
