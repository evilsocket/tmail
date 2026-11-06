#!/bin/sh
set -eu
umask 077
case "${1:-mail}" in
  mail) exec himalaya --config /config/himalaya.toml --account tmail mcp --allow-send;;
  events) exec node /channel/server.mjs --config /config/channel.json;;
  cli) shift; exec himalaya --config /config/himalaya.toml --account tmail "$@";;
  *) echo 'Expected mail, events, or cli.' >&2; exit 1;;
esac
