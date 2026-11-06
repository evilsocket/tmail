# tmail: instructions for AI assistants

Use this runbook when the user requests setup or operation of this checkout.
Reading it during a documentation or code-editing task does not authorize a live
deployment. Complete the work the user requested; ask only for missing details
or account interactions you cannot perform. Reuse existing authorization rather
than repeatedly asking to continue. Run host commands from the repository root.

## Deployment contract

- Docker is the only installed tmail dependency on server and agent hosts. Run
  setup, cryptographic tools, builds, mail tools, and event bridges in containers.
  Do not install host Tailscale, OpenSSL, Rust, Himalaya, Node, npm, Python, or age.
  The supplied host wrappers use ordinary OS shell utilities and Docker only.
- Server Docker Compose runs three services: `tailscale`, `mail` (Stalwart 1.0.3), and
  `maintenance`. Use the pinned images/assets in `Dockerfile`; do not substitute
  latest versions or install a different mail stack during setup.
- The dedicated Tailscale node is `tmail`. Its exact hostname is
  `tmail.<tailnet>.ts.net`; mailbox addresses use `tmail.internal`.
- Clients use SMTP **465**, IMAP **993**, and HTTPS **443**, all with TLS and
  certificate verification. Account administration is at `/admin`.
- No host ports, public MX, Funnel, subnet routing, exit node, or public MCP
  endpoint. Keep mail on the internal Docker network with its loopback resolver.
- **Custom Tailscale ACLs, tags, and host disk encryption are optional.** Do not
  add setup gates for them. The existing tailnet policy applies; with the usual
  allow-all policy, every tailnet device can reach the login endpoints. Mailbox
  and administrator credentials are still required. See `docs/access-control.md`
  if the user requests device-level restrictions; do not change the whole
  tailnet policy as part of basic setup.
- Agent mailboxes are ordinary Users, never administrators. Default to 1 GiB disk
  quota, unique random passwords, no aliases/groups/forwarding/Sieve. The server
  enforces 10 MiB messages, 20 distinct recipients, and 60 submissions/minute.
- Agent mailboxes are opt-in. Only `admin`, `owner`, and `maintenance` are
  bootstrapped automatically. Never create sample accounts or infer mailbox
  names from examples, installed AI clients, or this runbook.
- After every agent mailbox creation, including later account-management
  requests, guide the user through the MCP bridge workflow under
  [Client configuration](#client-configuration). Do not end at credentials alone.
- Owner↔agent email is allowed. Agent↔agent email needs directed server-side
  grants. Knowing another address does not grant permission. Keep this mail
  policy distinct from the optional Tailscale network policy.

## Secrets and existing installations

Never print passwords, auth keys, private keys, message bodies, or credential
request JSON in tool output or chat. Do not put secret values in shell arguments,
history, tracked files, or MCP config. Use protected files, a secret store, stdin,
and the recipes below. Disable shell tracing. Do not `source .env` as shell code.

Inspect `.env`, file existence/permissions, `docker compose ps`, and existing
volumes before creating anything. Do not overwrite working configuration, reset
passwords, regenerate `.secrets/blob_key`, or delete volumes to fix startup.
`scripts/setup.sh` preserves existing files, including an existing `.env`; update
its non-secret values deliberately if necessary. Initial account secrets may no
longer match passwords subsequently changed in the WebUI.

`.secrets/` is 0700. Its four server-readable secrets are 0444 within that private
directory so bind mounts work for container UID 2000; the auth key file is 0644.
Additional agent credential files should be 0600 in a 0700 directory. Never copy
the administrator credential or blob key to an agent node. Keep temporary admin
requests in the mail container's private `/run/tmail` tmpfs and clean them up.

## First setup or resuming an interrupted setup

1. Check `docker version` and `docker compose version`.
   Supported hosts are Linux Docker Engine and macOS Docker Desktop, with Compose
   v2 or newer. Start an installed Docker engine/Desktop if needed and within the
   user's request. If installation or an account login is needed, tell the user
   exactly what remains; continue independent preparation where possible.
2. Determine the exact tmail FQDN. Reuse `.env` or an enrolled container's status.
   Use the Tailscale web console or existing container status to identify the DNS
   suffix; do not install a host Tailscale client or dump peer inventories. Ask for the FQDN if unknown.
   Do not invent a suffix or assume the Docker host is the dedicated tmail node.
   Unless the user already made an explicit choice, ask: **"Would you like
   mailboxes for any AI agents now? If so, which agents and which mailbox names
   should they use?"** Choosing no agent mailboxes is valid. Wait for the answer
   before creating any; continue independent server setup while waiting. No
   answer is not consent. Do not ask again if names or an opt-out were already
   given. If multiple agents were selected, ask whether any should be allowed
   to email each other and in which directions, unless already specified.
   Default to no agent-to-agent grants. Keep existing accounts and grants intact.
3. Ensure MagicDNS and HTTPS certificates are enabled in the Tailscale admin
   console. Have the user create a non-ephemeral, preauthorized auth key if no
   enrolled state exists. Basic setup needs no tags. Node approval may require
   their login. **PRIVACY NOTE: Certificate issuance publishes the tmail hostname
   in certificate-transparency logs.** Explain this before first issuance.
4. Run `./scripts/setup.sh tmail.ACTUAL-TAILNET.ts.net`, substituting the real
   lowercase hostname. Have the user enter the auth key into
   `.secrets/tailscale_authkey` locally, or copy it from an authorized secret store
   without displaying it. Ask for a local secret-file path, not a key pasted into
   chat. On an already enrolled deployment an empty auth-key file is sufficient.
   Set `TMAIL_HOSTNAME` in `.env` to the exact hostname. If the default Docker
   subnet conflicts, change `TMAIL_SUBNET` and all three backend IPs together.
5. Validate, start, and inspect:

   ```sh
   docker compose config --quiet
   docker compose up -d --build
   docker compose ps
   docker compose logs --tail=30 tailscale maintenance mail
   docker compose exec -T tailscale tailscale status
   docker compose exec -T tailscale tailscale serve status
   docker compose exec -T mail /opt/tmail/scripts/mail-health.sh
   ```

   Allow time for enrollment, certificate issuance, and recovery-mode bootstrap.
   Use bounded status checks. Missing certificates keep mail waiting; an initial
   maintenance reload failure is retried. Verify the actual node hostname: a
   collision can result in a suffixed name. Resolve the node name/config mismatch
   rather than disabling hostname verification. Check existing network rules if
   a tailnet connection is denied; do not silently broaden them.
6. Verify the three services are healthy and no host ports are published. From
   an allowed tailnet device, verify trusted HTTPS at `/admin` and SMTP/IMAP TLS.
   Use `admin@tmail.internal` for administration and `owner@tmail.internal` for
   the human inbox. Their initial passwords are in the corresponding `.secrets`
   files; tell the user the paths, not their contents. Create only the selected
   agent accounts and requested peer grants as described below. After each new
   mailbox, guide its MCP bridge configuration, even during first-time setup.
7. When test email was requested, send synthetic messages between the specified
   local accounts and verify receipt/reply, including a denied peer if relevant.
   Do not send messages merely because this file includes testing instructions.
   Report what was actually verified, pending user steps, account addresses,
   credential-file locations, and the admin URL. Do not claim real tailnet, GUI,
   or scheduling tests passed based on offline Docker tests.

## Administration from the existing container

The WebUI supports account and lookup management. For headless operation, use
the native Stalwart management API below; no host CLI installation is needed.
Port 8444 is internal HTTPS, not an additional tailnet endpoint. `--resolve`
connects to loopback while retaining hostname and certificate verification.

Run the following shell snippets **inside** `docker compose exec mail sh`.
For noninteractive tools, combine the helper definitions and desired operation
in one `docker compose exec -T mail sh -s <<'SH' ... SH` invocation. Use a quoted
heredoc so the host does not expand container variables. Redirection in these
snippets writes container tmpfs files, not host files.

The helper uses `/run/secrets/admin_password`. If the password was changed,
obtain the current one through a protected local file and stream it into tmpfs:

```sh
# Host shell; substitute the authorized local password-file path.
docker compose exec -T mail sh -c 'umask 077; cat > /run/tmail/admin-password' \
  < /secure/path/current-admin-password
```

Set `TMAIL_ADMIN_PASSWORD_FILE=/run/tmail/admin-password` in the container shell
for that session; remove the temporary file afterward. A 401 means the credential
is wrong: do not reset the administrator account as a workaround.

```sh
# tmail-admin-functions
set -eu
umask 077

# Input: one JSON argument object on stdin. Output: the method result as JSON.
admin_call() (
  set -eu
  work=$(mktemp -d /run/tmail/admin-call.XXXXXX)
  trap 'rm -rf "$work"' EXIT
  jq -ce --arg method "$1" '{using:["urn:ietf:params:jmap:core"],
    methodCalls:[[$method,.,"op"]]}' > "$work/request.json"
  password=$(cat "${TMAIL_ADMIN_PASSWORD_FILE:-/run/secrets/admin_password}")
  credential=$(printf 'admin@tmail.internal:%s' "$password" | base64 -w 0)
  printf 'header = "Authorization: Basic %s"\n' "$credential" > "$work/auth"
  unset password credential
  curl --silent --show-error --fail --max-time 30 --config "$work/auth" \
    --resolve "$TMAIL_HOSTNAME:8444:127.0.0.1" -H 'Content-Type: application/json' \
    --data-binary @"$work/request.json" "https://$TMAIL_HOSTNAME:8444/jmap" \
    > "$work/response.json"
  jq -e --arg method "$1" '
    .methodResponses[0] as $r |
    if $r[0] == $method and
       ([$r[1].notCreated, $r[1].notUpdated, $r[1].notDestroyed] |
        all(. == null or . == {}))
    then $r[1] else error("Stalwart rejected the operation; inspect errors privately") end
  ' "$work/response.json"
)

# Query all IDs, then fetch records. Fail rather than return a misleading partial list.
list_objects() (
  set -eu
  work=$(mktemp -d /run/tmail/admin-list.XXXXXX)
  trap 'rm -rf "$work"' EXIT
  printf '%s\n' '{"limit":1000,"calculateTotal":true}' |
    admin_call "x:$1/query" > "$work/query.json"
  jq -e '.total != null and .total == (.ids | length)' "$work/query.json" >/dev/null || {
    echo 'Result needs pagination: query using position/limit until total is reached.' >&2
    exit 1
  }
  jq '{ids:.ids}' "$work/query.json" > "$work/get.json"
  admin_call "x:$1/get" < "$work/get.json" > "$work/result.json"
  jq '.list' "$work/result.json"
)
```

These helpers check both HTTP and JMAP errors; HTTP 200 alone is not success.
Do not print raw API requests or full account records containing credentials.
For large installations, paginate queries and collect all IDs before checking
whether an account or peer grant exists; never infer absence from a partial page.

## Create and inspect agent mailboxes

Create only the mailbox names the user requested. If they asked for agent mail
without choosing names, ask which agents need mailboxes and the name for each.
Use a simple lowercase local part chosen by the user; examples elsewhere in the
repository are not defaults. Reserve `admin`, `owner`, and `maintenance`. Query
the domain and accounts first; preserve an existing matching account and password.
Use User roles, inherited permissions, and `1073741824` bytes of disk quota.
Stalwart has no global disk-quota default, so set this explicitly for every user.

Inside the container, after defining the helpers, set `TMAIL_AGENT_NAME` to the
user's selected local part. This recipe fails if a name was not supplied:

```sh
# tmail-create-mailbox
(
  set -eu
  umask 077
  mailbox=${TMAIL_AGENT_NAME:?Set TMAIL_AGENT_NAME to the mailbox name chosen by the user}
  printf '%s' "$mailbox" | grep -Eq '^[a-z0-9][a-z0-9._-]{0,63}$'
  case "$mailbox" in admin|owner|maintenance) echo 'Reserved account name' >&2; exit 1;; esac
  work=$(mktemp -d /run/tmail/create-mailbox.XXXXXX)
  trap 'rm -rf "$work"' EXIT
  list_objects Domain > "$work/domains.json"
  domain_id=$(jq -er '[.[] | select(.name=="tmail.internal")] |
    if length==1 then .[0].id else error("Expected exactly one tmail domain") end' "$work/domains.json")
  list_objects Account > "$work/accounts.json"
  if jq -e --arg name "$mailbox" --arg domain "$domain_id" \
    'any(.[]; .name==$name and .domainId==$domain)' "$work/accounts.json" >/dev/null; then
    echo 'Mailbox already exists; credentials preserved.'
    exit 0
  fi
  password_file="/run/tmail/$mailbox-password"
  [ ! -e "$password_file" ] || { echo 'A pending credential file already exists.' >&2; exit 1; }
  openssl rand -base64 32 > "$password_file"
  jq -n --arg name "$mailbox" --arg domain "$domain_id" --rawfile password "$password_file" \
    '{create:{mailbox:{"@type":"User",name:$name,domainId:$domain,
      roles:{"@type":"User"},permissions:{"@type":"Inherit"},aliases:{},memberGroupIds:{},
      quotas:{maxDiskQuota:1073741824},
      credentials:{"0":{"@type":"Password",secret:($password|rtrimstr("\n"))}}}}}' \
    > "$work/create.json"
  admin_call x:Account/set < "$work/create.json" > "$work/created.json"
  jq -er '.created.mailbox.id' "$work/created.json"
)
```

On success, save the password without displaying it. Set `TMAIL_AGENT_NAME` to
that same chosen local part in the **host** shell, then run this before any
container restart:

```sh
(
  set -eu
  umask 077
  mailbox=${TMAIL_AGENT_NAME:?Set TMAIL_AGENT_NAME to the mailbox name chosen by the user}
  printf '%s' "$mailbox" | grep -Eq '^[a-z0-9][a-z0-9._-]{0,63}$'
  mkdir -p .secrets/agents
  chmod 700 .secrets/agents
  set -C # Refuse to overwrite an existing credential file.
  docker compose exec -T mail cat "/run/tmail/$mailbox-password" \
    > ".secrets/agents/${mailbox}_password"
)
```

Verify the saved file is nonempty and mode 0600, then remove the container copy.
Transfer only this credential to its intended agent using a protected local file
or secret store. If account creation failed or the account already existed, do
not distribute a newly generated password as though it belongs to that account.

After each successful creation, continue to [Client configuration](#client-configuration)
and guide the user through connecting this mailbox. This applies equally to
first setup and later requests to add an account. If an existing mailbox was
preserved on a retry, resume any unfinished bridge setup without resetting it.

List safe account details with:

```sh
list_objects Account | jq '.[] | {id,name,domainId,roles,quotas}'
```

## Allow or revoke agent-to-agent email

Use exact `MemoryLookupKey` records with namespace `tmail-peers`, key
`sender@tmail.internal|recipient@tmail.internal`, and `isGlobPattern:false`.
Check both mailbox addresses exist. A two-way conversation needs two directed
records; create only the directions the user requested. Before creating a grant,
query existing records and skip an exact match to make retries idempotent.
Never grant communication between every new mailbox by default. If the desired
directions are unclear, ask; creating accounts alone does not authorize grants.

```sh
list_objects MemoryLookupKey | jq '.[] | select(.namespace=="tmail-peers")'
```

For a missing, requested grant, set `TMAIL_PEER_SENDER` and `TMAIL_PEER_RECIPIENT`
to the chosen full email addresses inside the same container shell:

```sh
# tmail-grant-peer
(
  set -eu
  sender=${TMAIL_PEER_SENDER:?Set TMAIL_PEER_SENDER to the requested sender address}
  recipient=${TMAIL_PEER_RECIPIENT:?Set TMAIL_PEER_RECIPIENT to the requested recipient address}
  for address in "$sender" "$recipient"; do
    printf '%s' "$address" | grep -Eq '^[a-z0-9][a-z0-9._-]{0,63}@tmail\.internal$'
  done
  jq -n --arg key "$sender|$recipient" \
    '{create:{peer:{namespace:"tmail-peers",key:$key,isGlobPattern:false}}}' |
    admin_call x:MemoryLookupKey/set
  printf '%s\n' '{"create":{"reload":{"@type":"ReloadLookupStores"}}}' |
    admin_call x:Action/set
)
```

For revocation, obtain the matching record's actual ID from the query. Submit
`{"destroy":["ACTUAL_GRANT_ID"]}` to `admin_call x:MemoryLookupKey/set`, then run
`ReloadLookupStores` again. For a two-way revocation, remove both matching IDs.
Keep unrelated grants. Verify the records and, when authorized, attempt a test
message in the revoked direction. Revocation does not remove already delivered mail.

## Client configuration

**Guide this workflow after every agent mailbox creation, during initial setup
and all later account-management sessions.** Reuse the user's stated choices;
ask only for missing details. Do not treat a working server or a saved password
as a connected agent.

1. Identify which AI client will use this mailbox and on which machine/OS.
   If unknown, ask the user. The bridge runs on that client machine, which must
   have Docker running. Do not assume it runs on the server host.
2. Follow `docs/clients.md`: run `scripts/setup-client.sh SERVER MAILBOX CLIENT-NAME`
   for the chosen existing mailbox, then fill only that client's protected
   password and Tailscale enrollment-key files. Build `compose.client.yaml` and
   start its `gateway`. This container supplies Tailscale; no host VPN or language
   runtime is needed. Approve its separate tailnet node if required, preserve
   existing access policy, and target its identity for optional ACLs/Allowed IPs.
   Preserve `.clients/CLIENT-NAME/`, its private permissions, and event state.
   Never copy server admin credentials or the blob key to a client machine.
3. Guide registration of the local stdio MCP server in the chosen client's
   configuration, preserving existing entries. When the user requests hands-on
   configuration and the target is accessible, carry it out. Otherwise provide
   concrete instructions for their client, OS, and paths, including any restart
   or tool-approval step they must perform. Do not stop at a documentation link.
   For Claude Code terminal users, also guide `docs/channels.md`: use the same
   built client image and configure that mailbox's `tmail-events` container,
   select permitted wake-up senders, and register it alongside Himalaya. Reuse
   explicit sender authorization; default to owner-only, with no agent peers
   inferred from examples. Respect a request for on-demand mail only. Guide the
   user through launching the interactive session with the documented channel
   flag and accepting its preview prompt; registration alone does not enable it.
4. Verify the bridge starts and the client discovers its mail tools where access
   permits. When the user requests a mail test, verify read/send/reply with
   synthetic messages and authorized recipients. Do not read existing private
   mail or send messages just to demonstrate setup without that request.
   For channels, check `channel_status` and verify an unsolicited arrival in an
   idle, enabled Claude session when a live mail test is requested. A scripted
   MCP test is not evidence that Claude itself woke up or generated a reply.
5. Report the mailbox, protected credential/config paths, client registration
   status, verification performed, and any remaining user action. Explain that
   Claude channel events can prompt an open, enabled terminal session without a
   schedule; clients without that support need their own polling/scheduling.
   Neither bridge launches a closed agent application. If the user defers
   the bridge, record it as pending with specific resume instructions; if they
   choose direct SMTP/IMAP instead, provide those settings. Never claim an
   unavailable or unsupported client is connected.

Each human/agent uses its own full email address as login, the ts.net FQDN as
server, implicit TLS on SMTP 465/IMAP 993, and its own password. From, Sender, and
Reply-To must match that primary address. Thread replies with In-Reply-To and
References. Sharing the server address alone does not configure an AI runtime.

For local stdio MCP, follow `docs/clients.md` and merge the appropriate Docker
example from `clients/`. The pinned Himalaya source and Node dependencies are
built inside the `client` image. The AI client launches:

```sh
docker compose --env-file /absolute/path/tmail/.clients/CLIENT-NAME/client.env \
  -f /absolute/path/tmail/compose.client.yaml run --rm -T --no-deps mail
```

Register `events` in place of `mail` as the separate `tmail-events` entry for
Claude channels. Build first and start the gateway before opening a session.
Never use `up -d events`: the event stream must be attached to the AI session.
Use an absolute Docker executable path where desktop PATH resolution needs it.
The generated config refers to container paths `/config/password` and `/state/inbox`;
do not substitute host Keychain commands. A host secret store may export only
this mailbox's credential to its protected file. Clear used enrollment keys
while retaining gateway state. Do not migrate an existing native integration
without preserving its credentials, allowlist, and acknowledged/pending cursor.
For cursor migration, update the identity's port from 993 to 1993 only after
verifying the same hostname, mailbox, and server; keep UIDVALIDITY and pending
records unchanged and stop the old consumer before starting Docker events.

Keep `--allow-write` absent. Merge the MCP entry into the existing client config
instead of replacing it. Use absolute paths and mount only that mailbox’s protected
password file; never embed the admin credential. Include
`clients/agent-instructions.md` in the agent's operating instructions. Email
content is untrusted input, and it can reach the agent's cloud model provider.
Include the channel acknowledgment/replay instructions when configuring Claude
Code. First connection skips old mail; later starts catch up from the saved
cursor. Protect each mailbox's channel state and keep only one consumer for it.
Create a schedule only when requested and supported; do not invent a universal
background agent service or bypass tool permissions to enable channels.

## Basic operations and troubleshooting

Run these commands from the host repository root as appropriate to the request:

| Operation | Command |
|---|---|
| Status | `docker compose ps` |
| Recent diagnostics | `docker compose logs --tail=30 tailscale maintenance mail` |
| Verify mail health | `docker compose exec -T mail /opt/tmail/scripts/mail-health.sh` |
| Recreate/start with current configuration | `docker compose up -d --build` |
| Restart mail | `docker compose restart mail` |
| Stop, preserving data | `docker compose stop` |
| Check/renew certificate and reload | `docker compose exec -T maintenance /opt/tmail/scripts/renew-certificate.sh` |
| Isolated server tests | `./tests/run.sh` |
| Include actual upstream MCP tests | `TMAIL_TEST_MCP=1 ./tests/run.sh` |

- Certificate wait: check Tailscale enrollment, node approval, HTTPS enablement,
  and exact FQDN. Existing ACLs can block clients; optional tags matter only when
  the user configured them. Do not disable TLS verification to make a check pass.
- Expired loaded certificate: maintenance can install a valid replacement even
  when HTTPS reload fails. Mail's local watchdog detects that combination within
  roughly 30 seconds and triggers a Compose restart through normal bootstrap.
  Check the served certificate and service status afterward; preserve the
  restart policy and do not bypass TLS verification or expose recovery HTTP.
- 401/login failure: use the correct full address and current password; bootstrap
  secret files may be stale after rotation. Never reset an account automatically.
- SMTP recipient denied: check the exact local recipient and directed peer key,
  reload lookups, and check the reverse direction if a reply fails. External
  recipients, aliases, plus addresses, and unauthorized peers are intentionally denied.
- Change a quota: fetch the selected account by its real ID, preserve its other
  quotas, and update through the WebUI or submit
  `{"update":{"ACTUAL_ACCOUNT_ID":{"quotas/maxDiskQuota":2147483648}}}` to
  `admin_call x:Account/set` (this example sets 2 GiB).
- Rotate a password when requested: edit the selected password credential via
  the WebUI, or fetch `x:Account/get` with the actual account ID and locate the
  Password entry's key in the `credentials` map. Patch
  `credentials/ACTUAL_ENTRY_KEY/secret` through `x:Account/set`, building the
  request with `jq --rawfile` from a protected new-password file. Preserve other
  credentials, MFA, and Allowed IPs; do not replace the entire credential
  collection. Update that agent's secret store/file and
  verify a new login. For maintenance, update `.secrets/maintenance_password` to
  match and restart maintenance; retain its restricted role and source IP.
- Delete an account only when the user explicitly requests that account's
  removal. Resolve and verify its actual ID first, remove related peer grants,
  reload lookups, and submit `{"destroy":["ACTUAL_ACCOUNT_ID"]}` to
  `admin_call x:Account/set`. Account deletion removes mail; do not use it for
  troubleshooting. Reserved accounts are recreated on startup and should remain.
- Restart reasserts the security baseline; ordinary accounts, passwords, messages,
  and peer records persist. Change tracked configuration deliberately if a server
  policy must survive restart. Do not suggest ad-hoc WebUI changes that bootstrap
  will overwrite.

## Backup, restore, recovery, and completion

When asked for a backup, use the cold-backup commands in `docs/operations.md`:
use the containerized tools image, stop the services, archive mail-data/mail-config and Tailscale state, capture the
deployment files, and save the blob key and credentials separately. Stream to an
encrypted backup destination using the user's recipient/key or existing backup
system. Resume services after backup, including after a failed backup attempt,
unless the user requested they remain stopped. Do not claim a backup succeeded
without checking every pipeline stage and the resulting archives.

Restore into empty replacement volumes using the original pinned versions and
the original blob key. Stop the source first so two copies do not use one
Tailscale identity. Restore data/config and Tailscale state before startup, then
verify old messages, credentials, and peers. Do not overwrite live data or run
`docker compose down -v` without explicit intent to delete it. Lost administrator
access uses the internal recovery procedure in `docs/operations.md`; never expose
recovery port 8080 or leave recovery credentials enabled in normal service.

Keep secrets and test artifacts out of Git. For documentation-only work, check
links/examples instead of deploying. For behavior changes, run the relevant
isolated tests; use `docs/testing.md` for the live acceptance checks. In the final
handoff distinguish configured, actually verified, and pending work, and give
the user usable addresses/paths without disclosing secrets.
