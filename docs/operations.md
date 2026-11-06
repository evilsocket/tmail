# Operations

## Normal lifecycle

```sh
docker compose up -d --build
docker compose ps
docker compose logs --tail=30 mail maintenance tailscale
docker compose restart mail
docker compose stop
```

`up` and `restart` preserve the volumes. `docker compose down` also preserves
named volumes; **do not use `down -v`** unless deliberately deleting all mail and
node identity. The server reasserts the security baseline at each start. Peer
lookup entries and ordinary account changes persist; broad server configuration
edits in the WebUI may be overwritten. Keep source configuration under review.

The default Compose project name is `tmail`. Persistent volumes are mail-data,
mail-config, certificates, and tailscale-state. tailscale-socket holds the local
daemon socket, not durable application data. Maintenance cannot mount mail-data.

The initial admin/owner passwords live in `.secrets`. Change user passwords in
the WebUI or your secret manager; restarts do not reset them. If changing the
maintenance credential, update its protected file to the same new password and
restart maintenance. Preserve its Allowed IPs restriction. Recreating a deleted
reserved account on restart uses the corresponding initial secret.

## Certificates and troubleshooting

Maintenance requests a certificate twice daily through `tailscale cert` and
retries failures every five minutes. Tailscale handles issuance eligibility and
renewal timing. Trigger a check manually with:

```sh
docker compose exec maintenance /opt/tmail/scripts/renew-certificate.sh
```

No renewal action has access to mailbox data. A valid replacement is installed
atomically, then the maintenance account invokes `ReloadTlsCertificates`. Failed
reloads are retried even if the files have not changed. Generation directories
are retained for recovery; after confirming a current certificate works, old
generations can be removed during maintenance, preserving the symlink target.

If the loaded certificate expires before renewal succeeds, HTTPS reload requests
cannot authenticate the old listener. A local watchdog in the mail container
checks every 30 seconds: only when the on-disk certificate/key pass validation
and the loopback HTTPS listener fails certificate verification does it terminate
Stalwart gracefully. Compose's `unless-stopped` policy restarts mail through its
normal bootstrap, which loads the replacement. Connections are briefly
interrupted. No TLS verification is disabled, no plaintext management endpoint
is added, and maintenance receives no Docker socket or extra permissions.

If mail is waiting for a certificate, inspect Tailscale's state/hostname and
maintenance logs. Check MagicDNS, HTTPS enablement, node approval, exact FQDN,
and the auth key. If you use the optional ACL setup, also check its policy and
device tags. If only reload fails, verify the maintenance
password and fixed backend IP. Do not use `--insecure`, turn on plaintext, or
enable Funnel as a workaround. A certificate for the wrong node name is rejected.

Initial recovery's diagnostics are deliberately private and temporary. For a
failed startup, inspect `/run/tmail/apply.log` inside the container for the failed
configuration operation; do not publish credential plans or recovery logs. A
failed apply exits before opening normal listeners. The restart policy retries.

## Encrypted cold backup

Use an encrypted destination and an independently stored `age` decryption key.
The example runs [age](https://github.com/FiloSottile/age) and tar in the
`tools` image; no host age/OpenSSL installation is needed. Run these commands in **bash with
`set -euo pipefail`**, so a failed tar/encryption command cannot masquerade as a
successful backup. Keep the surrounding subshell and cleanup traps: services
resume on success, pipeline failure, or an interrupt, and the command retains a
nonzero status when backup or resumption fails. Fill in your age recipients,
never a private key in a command.

```bash
(
set -euo pipefail
umask 077
docker build --target tools -t tmail-tools:local .
tool() {
  docker run --rm -i --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=$PWD,dst=/workspace,readonly" tmail-tools:local "$@"
}
backup_dir="backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
mail_recipient='age1REPLACE_WITH_BACKUP_RECIPIENT'
key_recipient='age1REPLACE_WITH_SEPARATE_KEY_CUSTODY_RECIPIENT'

resume_services() {
  backup_status=$?
  trap - EXIT HUP INT TERM
  if docker compose up -d; then
    :
  else
    resume_status=$?
    echo 'Could not resume tmail; run docker compose up -d and check its status.' >&2
    if [ "$backup_status" -eq 0 ]; then backup_status=$resume_status; fi
  fi
  exit "$backup_status"
}
trap resume_services EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
docker compose stop
docker compose run --rm -T --no-deps --entrypoint tar mail \
  -C / -cf - var/lib/stalwart etc/stalwart |
  tool age -r "$mail_recipient" > "$backup_dir/mail.tar.age"
docker compose run --rm -T --no-deps --entrypoint tar tailscale \
  -C /var/lib/tailscale -cf - . |
  tool age -r "$mail_recipient" > "$backup_dir/tailscale.tar.age"
tool tar --exclude='*/node_modules' --exclude='*/__pycache__' -cf - \
  .env .env.example .dockerignore .gitignore compose.yaml compose.client.yaml \
  Dockerfile config scripts clients |
  tool age -r "$mail_recipient" > "$backup_dir/deployment.tar.age"
tool tar -C .secrets -cf - blob_key admin_password owner_password maintenance_password |
  tool age -r "$key_recipient" > "$backup_dir/secrets.tar.age"
)
```

A force kill, host crash, or unavailable Docker daemon can prevent cleanup;
check service status manually in those cases. Treat files from any failed run
as incomplete and retain your previous known-good backup.

Keep `secrets.tar.age` and its decryption identity in separate custody from the
mail backup. Do not delete or replace `blob_key`. These backups contain metadata,
credentials/hashes, and Tailscale identity; encryption is recommended even though
email blobs are already encrypted. Certificates can be reissued from the restored
Tailscale identity, so the certificate and socket volumes need not be archived.
The auth key is not needed to restore an enrolled node.

Test decryption and restoration periodically. Do not delete the last known good
backup after merely checking that new archive files exist. Capture the source
revision and image digests alongside the encrypted deployment archive.

## Restore on an isolated replacement host

Stop the source deployment first: two running copies must not share a Tailscale
identity. Start with empty replacement volumes. Optionally enable host disk
encryption before restoring for additional protection of metadata and secrets. Restore
the deployment archive into a new directory, restore `.secrets` from the separate
secret archive, and restore its 0700 directory / 0444 mail-secret permissions.
Create an empty readable `tailscale_authkey` file. Do not start services yet.

```bash
# In the restored checkout, using the original pinned image versions:
set -euo pipefail
docker compose build
docker build --target tools -t tmail-tools:local .
decrypt() {
  docker run --rm -i --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --user "$(id -u):$(id -g)" \
    --mount type=bind,src=/secure/path/backup-identity,dst=/run/age-identity,readonly \
    tmail-tools:local age -d -i /run/age-identity
}
decrypt < mail.tar.age |
  docker compose run --rm -T --no-deps --entrypoint tar mail -C / -xf -
decrypt < tailscale.tar.age |
  docker compose run --rm -T --no-deps --entrypoint tar tailscale -C /var/lib/tailscale -xf -
docker compose up -d
```

Validate the node identity, TLS, existing login passwords, peer permissions, and
read several old messages. The offline acceptance suite exercises a cold data
copy/restore with the original separately held blob key. A real encrypted
archive/host migration still needs testing with your backup system.

## Updates and recovery

All upstream image references and application assets are pinned in `Dockerfile`.
Review upstream release notes and schema changes, update pins/checksums together,
build, and run acceptance tests before updating a live deployment. Take a cold
backup first. Do not assume a database opened by a newer version can be rolled
back; restore the matching backup for a downgrade.

If administrator access is lost, use a controlled local recovery session: stop
mail, temporarily run its image with `STALWART_RECOVERY_MODE=1` and a freshly
generated recovery credential, only on the existing private backend with **no
ports or Serve mapping to 8080**. Use the bundled CLI inside that container to
reset the selected account credential, then stop the recovery process and resume
normal Compose startup without those variables. Never add persistent recovery
credentials to `.env` or expose recovery over Tailscale. Preserve the data volume
and blob key throughout. See Stalwart's [recovery/declarative deployment guidance](https://stalw.art/docs/configuration/declarative-deployments/).
