#!/bin/sh
set -eu
cert=/certificates/current/fullchain.pem
key=/certificates/current/privkey.pem
[ -r "$cert" ] && [ -r "$key" ]
openssl x509 -in "$cert" -noout -checkend 0 >/dev/null
openssl x509 -in "$cert" -noout -checkhost "$TMAIL_HOSTNAME" >/dev/null
openssl verify -CAfile "${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}" \
  -untrusted "$cert" "$cert" >/dev/null
# Hash the DER public keys, without writing private material to disk.
cert_key=$(openssl x509 -in "$cert" -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256)
private_key=$(openssl pkey -in "$key" -pubout -outform DER | openssl dgst -sha256)
[ "$cert_key" = "$private_key" ]
