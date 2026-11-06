#!/bin/sh
# Real certificate validation and atomic installation; synthetic Tailscale/API IO.
set -eu
umask 077
mkdir -p /tmp/mockbin /tmp/good1 /tmp/good2 /tmp/bad /run/tmail
export TMAIL_HOSTNAME=tmail.test.ts.net TS_SOCKET=/tmp/nonexistent-test-socket
export SSL_CERT_FILE=/tmp/ca.pem
openssl req -x509 -newkey rsa:2048 -noenc -days 3 -subj /CN=tmail-test-ca \
  -keyout /tmp/ca.key -out /tmp/ca.pem -addext basicConstraints=critical,CA:TRUE \
  -addext keyUsage=critical,keyCertSign,cRLSign 2>/dev/null
printf 'subjectAltName=DNS:%s\nextendedKeyUsage=serverAuth\n' "$TMAIL_HOSTNAME" > /tmp/extensions
for n in 1 2; do
  openssl req -new -newkey rsa:2048 -noenc -subj "/CN=$TMAIL_HOSTNAME" \
    -keyout "/tmp/good$n/privkey.pem" -out /tmp/request 2>/dev/null
  openssl x509 -req -in /tmp/request -CA /tmp/ca.pem -CAkey /tmp/ca.key -set_serial "$n" \
    -days 3 -extfile /tmp/extensions -out "/tmp/good$n/fullchain.pem" 2>/dev/null
done
printf 'synthetic-maintenance-password\n' > /run/secrets/maintenance_password
cat > /tmp/mockbin/tailscale <<'MOCK'
#!/bin/sh
set -eu
[ "${TEST_ISSUANCE_FAIL:-0}" != 1 ] || exit 1
for arg in "$@"; do
  case "$arg" in
    --cert-file=*) cp "$TEST_CERT_SOURCE/fullchain.pem" "${arg#*=}";;
    --key-file=*) cp "$TEST_CERT_SOURCE/privkey.pem" "${arg#*=}";;
  esac
done
MOCK
cat > /tmp/mockbin/curl <<'MOCK'
#!/bin/sh
[ "${TEST_RELOAD_FAIL:-0}" != 1 ] || exit 22
printf '%s\n' '{"methodResponses":[["x:Action/set",{"created":{"reload":{"id":"synthetic"}}},"reload"]]}'
MOCK
chmod 755 /tmp/mockbin/*
export PATH="/tmp/mockbin:$PATH"
export TEST_CERT_SOURCE=/tmp/good1
if /opt/tmail/scripts/cert-health.sh 2>/dev/null; then echo 'FAIL missing certificate accepted'; exit 1; fi
echo 'PASS missing certificate fails health/startup gate'
/opt/tmail/scripts/renew-certificate.sh
first=$(readlink /certificates/current)
/opt/tmail/scripts/cert-health.sh >/dev/null
echo 'PASS trusted matching certificate installed atomically'
if TEST_ISSUANCE_FAIL=1 /opt/tmail/scripts/renew-certificate.sh 2>/dev/null; then exit 1; fi
[ "$(readlink /certificates/current)" = "$first" ]
echo 'PASS issuance failure retains current certificate'
cp /tmp/good1/fullchain.pem /tmp/bad/fullchain.pem
cp /tmp/good2/privkey.pem /tmp/bad/privkey.pem
if TEST_CERT_SOURCE=/tmp/bad /opt/tmail/scripts/renew-certificate.sh 2>/dev/null; then exit 1; fi
[ "$(readlink /certificates/current)" = "$first" ]
echo 'PASS mismatched key rejected before installation'
if TMAIL_HOSTNAME=wrong.test.ts.net /opt/tmail/scripts/renew-certificate.sh 2>/dev/null; then exit 1; fi
[ "$(readlink /certificates/current)" = "$first" ]
echo 'PASS wrong-host certificate rejected before installation'
export TEST_CERT_SOURCE=/tmp/good2
if TEST_RELOAD_FAIL=1 /opt/tmail/scripts/renew-certificate.sh 2>/dev/null; then exit 1; fi
[ "$(readlink /certificates/current)" != "$first" ]
/opt/tmail/scripts/renew-certificate.sh
echo 'PASS failed reload retries successfully with unchanged new certificate'
[ ! -e /run/tmail/curl-auth ]
echo 'PASS temporary reload credential file removed'
