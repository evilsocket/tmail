# tmail

Private, standard email between you and agents on your Tailscale network. Stalwart
provides SMTP, IMAP, storage, and a web administration UI; Tailscale provides the
private network. Server setup and agent MCP/event bridges run in Docker; no
additional tmail dependencies are installed on either host. There is no custom
mail server, messaging broker, or agent runner.

## Email server AI-assisted setup

After cloning this repository, open it in an AI coding assistant with terminal
access and ask it to follow [AGENTS.md](AGENTS.md). The guide covers setup, creating
agent mailboxes, granting or revoking peer communication, and routine operations.
If your assistant does not automatically read `AGENTS.md`, explicitly ask it to
read the file first.

For example:

> Read AGENTS.md and set up the tmail email server on this machine. Ask whether
> I want mailboxes for AI agents and, if so, which agents and mailbox names to
> use. Ask which agents should be allowed to email each other. After creating each mailbox,
> guide me through configuring its MCP bridge for my chosen client and machine.
> Ask for missing Tailscale details or steps that need my login. Keep passwords
> and auth keys out of the conversation.

Agent mailboxes are opt-in: no sample agent accounts or peer grants are created
by default. Basic setup creates only the reserved `admin`, `owner`, and
`maintenance` accounts. You can choose no agent mailboxes and add them later.
The assistant also guides MCP bridge setup whenever you add a mailbox later;
creating a mailbox alone does not connect an AI client or enable automatic replies.

Docker and access to your Tailscale account are still needed. The assistant can
prepare configuration and run the deployment; you may need to enable Tailscale
HTTPS certificates, approve the node, or enter an auth key locally. Custom ACLs
and host disk encryption are optional. **PRIVACY NOTE: Certificate issuance
publishes the tmail hostname in certificate-transparency logs.**

For later work, ask for operations such as “create a planner mailbox,” “revoke
researcher's permission to email coder,” or “check tmail's health.”

## Email server manual setup

On the server host, clone this repository and start Docker with Compose v2
(Linux Docker Engine or macOS Docker Desktop). Run commands from the repository
root. Allow about 2 GiB RAM for mail plus the two small sidecars.

1. **Prepare Tailscale.** Enable MagicDNS and HTTPS certificates, reserve the
   node name `tmail`, and create a non-ephemeral, preauthorized auth key.
   **PRIVACY NOTE: Certificate issuance publishes that hostname in
   certificate-transparency logs.**
2. **Prepare configuration**, replacing the placeholder with your actual hostname:

   ```sh
   ./scripts/setup.sh tmail.YOUR-TAILNET.ts.net
   ```

   Save the key in `.secrets/tailscale_authkey` using an editor or secret manager,
   never chat or shell history. If `172.30.240.0/28` conflicts, change the subnet
   and all three backend IPs together in `.env`.
3. **Start the server and check it:**

   ```sh
   docker compose up -d --build
   docker compose ps
   docker compose exec tailscale tailscale status
   ```

   Approve the node if requested, wait for all three services to be healthy,
   and verify the assigned hostname matches `.env`.
4. **Sign in.** Open `https://tmail.YOUR-TAILNET.ts.net/admin` from a browser with
   tailnet access; use `admin@tmail.internal` and `.secrets/admin_password`.
   For Docker-only headless administration, use the
   [container runbook](AGENTS.md#administration-from-the-existing-container).
   Your own inbox uses `owner@tmail.internal`, `.secrets/owner_password`, and the
   [connection settings](#connection-settings) below.
5. **Create only the agent mailboxes you want**, following
   [accounts and peer permissions](#accounts-and-peer-permissions). Connect each
   mailbox using the agent MCP setup below.

Keep generated secret permissions unchanged; never copy the server's `.secrets`
directory to agent machines. Existing tailnet rules must allow mail access on
465/993 and administration on 443. Custom ACLs and disk encryption remain
optional; never enable Funnel, subnet routing, or exit-node functionality.

## Agent MCP AI-assisted setup

On the machine running your AI agent, clone this repository and open it in an
assistant with terminal access. Have an existing tmail server and an ordinary
agent mailbox ready, then ask:

> Read AGENTS.md and follow its Client configuration section to set up the
> Docker-only agent MCP stack on this machine. Ask for the server hostname,
> existing mailbox name, AI application, and a unique client name. Reuse my
> mailbox credentials and guide me through entering secrets locally. Build the
> client images, start its Tailscale gateway, and register the mail MCP command
> in my AI application. For Claude Code, ask whether I want incoming-mail events
> and which senders may wake the session, then configure the event bridge if
> requested. Preserve existing MCP entries and event state. Keep passwords and
> auth keys out of the conversation, and report any remaining activation steps.

The client stack runs Tailscale, Himalaya, and the event bridge in Docker. No host
VPN, Node, npm, or Rust installation is needed. Each mailbox gets its own client
configuration, credentials, tailnet identity, and persistent event state. MCP
uses local stdio; sending and replying are enabled, destructive tools disabled.

## Agent MCP manual setup

Run these steps on the agent's machine with Docker/Compose v2 and the cloned
repository. Use your actual server hostname, replace `YOUR-MAILBOX` with the
existing mailbox's local part, and choose a unique `YOUR-CLIENT` name using
lowercase letters, digits, and hyphens.

1. **Prepare the client files:**

   ```sh
   ./scripts/setup-client.sh tmail.YOUR-TAILNET.ts.net YOUR-MAILBOX YOUR-CLIENT
   ```

2. **Fill the protected files locally.** Save the mailbox password in
   `.clients/YOUR-CLIENT/mail/password` and a non-ephemeral Tailscale enrollment
   key in `.clients/YOUR-CLIENT/tailscale_authkey`. Keep the generated permissions;
   never put secrets in MCP configuration, chat, or shell history.
3. **Build and start the gateway:**

   ```sh
   docker compose --env-file .clients/YOUR-CLIENT/client.env -f compose.client.yaml build gateway mail events
   docker compose --env-file .clients/YOUR-CLIENT/client.env -f compose.client.yaml up -d gateway
   docker compose --env-file .clients/YOUR-CLIENT/client.env -f compose.client.yaml ps
   ```

   Approve the new `tmail-YOUR-CLIENT` node if requested and wait for it to be
   healthy. Existing access rules apply to this container's tailnet identity.
4. **Register `tmail` as a local stdio MCP server** in your AI application's
   settings, using this command with your actual absolute paths:

   ```sh
   /absolute/path/to/docker compose \
     --env-file /absolute/path/tmail/.clients/YOUR-CLIENT/client.env \
     -f /absolute/path/tmail/compose.client.yaml run --rm -T --no-deps mail
   ```

   Use `command -v docker` to find its executable path. Preserve other MCP
   entries. Example configuration formats:
   [Claude Desktop JSON](clients/claude-desktop.json.example) and
   [Codex TOML](clients/codex.toml.example).
5. **For Claude Code events (optional),** register the same command as
   `tmail-events`, replacing the final `mail` with `events`. Choose permitted
   `allowedSenders` in `.clients/YOUR-CLIENT/mail/channel.json` (owner-only by
   default), then start an interactive session and accept its channel prompt:

   ```sh
   claude --dangerously-load-development-channels server:tmail-events
   ```

6. **Verify the connection.** Confirm the mail tools appear in a new AI session.
   With events enabled, call `channel_status` and check `connected: true`.
   Keep Docker, the gateway, and the AI session running; the AI app starts and
   removes its MCP containers automatically.

Only enabled Claude Code terminal sessions use these push events; other clients
need their own supported polling/scheduling. Event acknowledgments survive
container removal. Include [agent-instructions.md](clients/agent-instructions.md)
in the agent's instructions. See the [client guide](docs/clients.md) for migration
and troubleshooting, and [channel details](docs/channels.md) for event behavior.

## Optional privacy and security hardening

These steps provide additional protection and are not required to start tmail:

- **Restrict which devices can connect with Tailscale ACLs.** Access control lists
  (ACLs) are network rules that decide which devices can reach a service and on
  which ports. The optional tmail policy lets selected devices use email and
  reserves the web administration endpoint for your administrator devices.

  **If you skip this:** your existing tailnet policy decides who can connect.
  With Tailscale's [default allow-all policy](https://tailscale.com/docs/features/access-control/acls),
  every device on your tailnet can reach SMTP, IMAP, and the admin login page.
  Mailbox access still requires its password, administration still requires an
  administrator login, and agent-to-agent email permissions still apply. However,
  any of those devices can attempt logins or attack the exposed services, so a
  compromised tailnet device has more opportunities to reach tmail. The service
  remains private to Tailscale; skipping ACL customization does not publish it
  to the internet or LAN. See the [optional ACL setup guide](docs/access-control.md).
- **Encrypt host storage.** Use LUKS or equivalent on Linux, or FileVault on macOS,
  including the disk containing Docker Desktop's VM, this checkout, and secrets.
  This protects metadata, indexes, and other files beyond the email blobs that
  tmail already encrypts. Host encryption is optional and needs no startup flag.
- **Limit enrollment-key reuse.** Choose single-use keys. After successful
  enrollment, clear the server's `.secrets/tailscale_authkey` or the client's
  `.clients/YOUR-CLIENT/tailscale_authkey` and revoke unused reusable keys.
  Persistent node state is used on subsequent starts.
- **Bind a mailbox to its node.** In the WebUI, restrict the mailbox password's
  Allowed IPs to that node's Tailscale IPv4 `/32` and IPv6 `/128`. This adds a
  per-mailbox node restriction, whether or not you customize Tailscale ACLs. See
  [security boundaries](docs/security.md).
- **Keep credential custody in a secret store.** Export only each agent's mailbox
  password into its protected client file for the read-only container mount.
  Do not mount an entire host keychain. See [client configuration](docs/clients.md).
- **Set up encrypted backups.** Keep backups off the server and the blob key in
  separate custody, then test restoration. See the
  [backup and restore procedure](docs/operations.md#encrypted-cold-backup).

## Connection settings

| Client setting | Value |
|---|---|
| Email / login | `owner@tmail.internal` or an agent's own address |
| Server hostname | `tmail.<your-tailnet>.ts.net` |
| SMTP submission | Port **465**, implicit TLS, password authentication |
| IMAP | Port **993**, implicit TLS, password authentication |
| Administration | `https://tmail.<your-tailnet>.ts.net/admin` |

No public MX, purchased domain, external email account, or host port is needed.
`tmail.internal` is the mailbox domain; clients must explicitly use the **ts.net
hostname** for their server and verify its TLS certificate. Internet email is
intentionally rejected, including mail submitted by authenticated accounts.

## Accounts and peer permissions

Use Stalwart's existing WebUI. Create a **User account** in `tmail.internal`, with
the **User** role, a unique random password (at least 16 characters), **1 GiB disk
quota**, no aliases, and no group memberships. `researcher` becomes
`researcher@tmail.internal`. Give each agent a separate mailbox and credentials.
The built-in User role is replaced by a narrowly scoped SMTP/IMAP role.

Stalwart 1.0.3 has no server-wide default disk-byte quota: **set the 1 GiB quota on
each new WebUI account**. Initial accounts and the supplied
[account template](config/new-account.json.example) use `1073741824` bytes. The
template requires the chosen mailbox name, domain ID, and a unique password;
its placeholders are not defaults. Use the container-based account-management
recipes in [AGENTS.md](AGENTS.md#create-and-inspect-agent-mailboxes), which require
no host CLI. Protect and remove temporary account JSON containing a password.

Owner-to-agent and agent-to-owner delivery is allowed. Agent-to-agent delivery
starts denied. To allow `researcher` to email `coder`, create an exact **Memory
lookup key** in the WebUI:

| Field | Value |
|---|---|
| Namespace | `tmail-peers` |
| Key | `researcher@tmail.internal\|coder@tmail.internal` |
| Glob pattern | **Off** |

The actual key contains one plain `|` character, without a backslash. Add the
reverse key `coder@tmail.internal|researcher@tmail.internal` for replies. Invoke
**Actions → Reload lookup stores** after adding, changing, or deleting entries.
For headless operation, use the container-based
[grant/revoke recipes](AGENTS.md#allow-or-revoke-agent-to-agent-email).

Every SMTP envelope
recipient is checked independently, including CC/BCC recipients. A client may
still deliver to allowed recipients when another recipient is rejected: SMTP
does not promise all-or-nothing multi-recipient delivery. Merely telling an agent
another address does not install permission; the administrator must add the pair.

Do not create aliases, groups, mailing lists, catch-alls, plus-address mappings,
forwarding, or user Sieve rules in v1. Users have no permissions to create these.
The startup baseline removes mailing lists, user Sieve scripts, hooks, and remote
delivery routes; it restores the fixed domain, roles, listeners, and security
policies. Ordinary accounts, credentials, messages, and peer entries persist.
The reserved `admin`, `owner`, and `maintenance` accounts are created only if absent.

Limits are 10 MiB per message, 20 distinct envelope recipients, 1 GiB per mailbox
when created as above, and 60 SMTP MAIL attempts per minute per account. The
server binds the envelope and From header to the authenticated primary address.
Sender and Reply-To, when present, must also match. Resent identity headers are
rejected. Use In-Reply-To and References for conversation threading.

## Operation and verification

- [Operations, backup, restore, and recovery](docs/operations.md)
- [Security boundaries and architecture](docs/security.md)
- [Automated tests and live acceptance checklist](docs/testing.md)
- [Upstream choices and pinned dependencies](docs/upstream.md)

Run `./tests/run.sh` for isolated, synthetic-mail acceptance tests. Optional
`TMAIL_TEST_MCP=1 ./tests/run.sh` also builds and exercises the pinned upstream
Himalaya MCP implementation. Tests publish no ports and require no Tailscale key.

Real tailnet authorization and certificate issuance require your configuration;
they are not claimed by the isolated tests. This repository does not configure
or launch your agent applications automatically.
