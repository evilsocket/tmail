# Validation

## Automated suite

```sh
./tests/run.sh
# Includes a pinned source build and actual stdio MCP operations:
TMAIL_TEST_MCP=1 ./tests/run.sh
# Local channel behavior and isolated real IMAP IDLE/MCP notification tests:
./tests/channel.sh
# Production client images, Compose stdio transport, and persistent event state:
./tests/client.sh
```

The suite builds disposable test images, uses fresh tmpfs storage and random
synthetic credentials, and publishes no ports. Protocol tests run with
`--network none`, a read-only root filesystem, no capabilities, no new privileges,
and CPU/memory/PID limits. Certificate script tests grant only CHOWN for the
production file ownership changes. They use real cryptographic validation with
synthetic issuance and reload transports. A separate internal Docker network
tests the production resolver configuration and lack of external connectivity.
Expired-certificate recovery uses real Stalwart/TLS with synthetic issuance;
the test restarts the entrypoint after watchdog shutdown to emulate Compose's
restart policy. Its temporary command stubs require an executable test tmpfs.
Backup cleanup tests execute the documented Bash recipe with stubbed Docker,
archive, and encryption commands, including failed commands and interrupts.
The suite does not read `.env`, `.secrets`, real mail volumes, or Tailscale state.

The client-container suite uses Docker's local socket in a **test controller
only**, to manage a unique disposable Compose project. The production MCP images
never receive that socket. It binds only the tests and synthetic temporary files,
uses internal test networks, and removes its own containers/volumes afterward.
Real Stalwart, Himalaya, Node, socat, TLS, and Compose stdio run in separate
containers. The tailnet transport is stubbed for this offline test; live gateway
enrollment and actual cross-node `tailscale nc` connectivity still need a tailnet
acceptance check. No host Python, Rust, Node, npm, or OpenSSL is needed for tests.

Validated on **2026-11-06, macOS Apple Silicon / Docker Desktop, Linux arm64
containers**:

- **56 protocol/lifecycle/MCP checks**: empty bootstrap without a host-encryption
  acknowledgement; TLS-only listeners;
  hostname and trust verification; closed recovery/plaintext ports; SMTP auth;
  envelope, From, Sender and Reply-To identity; malformed/multiple/missing From;
  denied unknown, external, plus-address, and unapproved recipients; CC/BCC
  envelope checks; directed peer grants and revocation; account administration
  denied to agents/maintenance; scoped certificate reload; IMAP mailbox
  isolation; message/recipient/quota/rate limits; forbidden mailbox sharing;
  bundled offline WebUI; restart/password/identity/policy persistence; blob-key
  configuration; PROXY v2 and forwarded-IP credential restrictions; live TLS
  certificate replacement; cold data backup restoration; real upstream MCP
  list/read/send/reply, with destructive tools absent, and received reply headers
  preserving both In-Reply-To and References.
- **7 certificate lifecycle checks**: missing certificate, valid atomic install,
  failed issuance, mismatched private key, wrong hostname, failed reload/retry,
  and cleanup of temporary credential material.
- **12 expired-certificate recovery checks**: an actually expired served
  certificate blocks HTTPS reload; invalid on-disk replacements cannot trigger
  a restart; maintenance installs a valid replacement; the watchdog exits mail;
  normal bootstrap restores verified TLS with accounts/credentials preserved;
  scoped reload works again and healthy listeners remain running.
- **13 backup cleanup checks**: successful backup, stop/archive/encryption/output
  failures, HUP/INT/TERM interruptions, and failed resumption. Every case attempts
  resumption once and preserves the appropriate exit status. These tests verify
  cleanup control flow, not actual archive encryption or host migration.
- **Internal network egress probe**: no default route; external IPv4 SMTP/HTTP/DNS
  and IPv6 connection attempts fail; DNS cannot use Docker's resolver.
- Compose validates with exactly three services, no host port mappings, an
  internal-only mail/maintenance network, dropped capabilities and read-only root
  filesystems. Setup reruns preserve secrets. Client JSON and TOML parse.
- Server and client production image targets build. A network-disabled smoke test starts
  Tailscale in userspace with the production capability/read-only restrictions;
  it reaches NeedsLogin without a TUN device, policy acknowledgement, or advertised
  tags. It does not enroll a node.
- **9 channel unit/protocol checks**: explicit configuration and credential
  protection; exact sender allowlist and self-mail suppression; exclusive state
  locking and corruption detection; initial cursor, replay and acknowledgments;
  pending-queue backpressure; reconnect and UIDVALIDITY handling; real MCP
  initialization and clean shutdown on stdin EOF.
- **14 isolated channel integration checks**: the actual Node bridge against
  Stalwart over verified IMAP TLS; unsolicited IDLE events following SMTP
  delivery; no subjects/bodies in notifications or Seen-flag mutation; independent
  wake-up allowlists; persistent acknowledgment and offline catch-up; concurrent
  consumer exclusion; server-restart reconciliation; rejection of untrusted and
  wrong-host TLS certificates; private state-file permissions. These are protocol
  tests, not a claim that a real Claude conversation reacted automatically.
- **14 production client-container checks**: Dockerized server/client setup
  preserves existing files; real gateway starts in userspace without TUN or
  capabilities; Compose exposes no host ports; non-root MCP containers use only
  their scoped mounts and internal network; real mail read/send/reply and
  unsolicited channel events cross the gateway over verified TLS; pending events
  replay and acknowledgments persist across container removal; stdio EOF cleans
  up both MCP containers. Tailnet forwarding is synthetic in this test.

Tests are intentionally synthetic. The CA used in tests is installed only in the
test process's trust configuration; production requires a publicly trusted
Tailscale certificate and has no insecure-TLS switch.

## Live acceptance before production

These checks require your tailnet, several node identities, and a real client.
They have **not** been executed by the offline suite:

1. Enroll the dedicated tmail server and verify its final hostname. No tags or
   policy changes are needed for a tailnet using the default allow-all policy.
   If you choose the optional ACL setup, install its policy with all allow/deny
   tests passing, audit overlapping rules, and assign the documented device tags.
2. From a device allowed by your existing tailnet policy, verify SMTP 465, IMAP
   993, and HTTPS 443. Confirm that mailbox and administrator credentials are
   still required. With the default allow-all policy, other tailnet devices can
   also reach these login endpoints. **For the optional ACL setup**, additionally
   verify that mail-only devices cannot reach HTTPS and unapproved devices cannot
   reach any of the three ports. Test both Tailscale IPv4 and IPv6. A network
   denial should never reach an SMTP/IMAP greeting or HTTP login page.
3. From LAN/public hosts, test the Docker host's IPv4 and IPv6 on 443, 465, and
   993. No tmail port should be reachable. Confirm `docker compose ps` has no
   published ports and `tailscale serve status` contains only the three forwards.
   Confirm Funnel, advertised routes, and exit-node functionality are absent.
4. Verify the chain and hostname from an authorized node, for example:

   ```sh
   docker compose --env-file .clients/YOUR-CLIENT/client.env -f compose.client.yaml \
     run --rm -T --no-deps --entrypoint node mail -e '
       const c = JSON.parse(require("fs").readFileSync("/config/channel.json"));
       const s = require("tls").connect({host:c.host, port:c.port, servername:c.host},
         () => { console.log("Verified TLS chain and hostname"); s.end(); });
       s.setTimeout(5000, () => s.destroy(new Error("Timeout")));
       s.on("error", () => { process.exitCode = 1; });
     '
   ```

   This uses the container trust store and the client gateway, without host
   OpenSSL or Tailscale. Test both tailnet address families separately with
   containerized network probes, retaining hostname/SNI verification.
5. Create two agent accounts with 1 GiB quotas. Exchange owner messages and
   threaded replies using your clients, add both directed peer grants, reload,
   exchange a peer conversation, remove a grant, and verify its revocation.
6. Run the local MCP bridge on each actual agent node. In each installed client,
   explicitly test list/read/new-send/threaded-reply and a denied peer. Verify
   the tool list lacks deletion/write tools. For Claude Code channels, use the
   [live channel procedure](channels.md): leave an enabled terminal session idle,
   deliver an authorized synthetic message, and observe an unsolicited event,
   model action, and acknowledgment. Verify restart replay and duplicate-reply
   handling. Test polling separately for clients using schedules, including
   what happens when the app is closed. Protocol tests alone do not demonstrate
   an actual Claude session waking up.
7. Reboot/recreate the containers and confirm the same tailnet identity,
   credentials, mail, and peer entries. Trigger maintenance, observe actual
   `tailscale cert` issuance/renewal, and verify the served certificate. Test a
   temporary maintenance failure without changing the valid certificate volume.
8. Restore an encrypted backup onto an isolated replacement host with the same
   separately held blob key. Do not run two copies of one Tailscale identity.

Native Linux-host deployment, linux/amd64 execution, public-CA/Tailscale issuance,
real IPv4/IPv6 tailnet ACL enforcement, GUI app sessions, and encrypted archive
migration remain **untested here**. The supplied CLI branches and OCI images
support both arm64 and amd64, but that is not a claim that both test matrices ran.
