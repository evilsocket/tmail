#!/bin/sh
set -eu
TS_AUTHKEY=$(cat /run/secrets/tailscale_authkey)
export TS_AUTHKEY
exec /usr/local/bin/containerboot
