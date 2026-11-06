# Clients and local MCP

SMTP on 465 and IMAP on 993, both implicit TLS with hostname/chain verification,
are the compatibility contract. Use your preferred mail client for your owner
mailbox. An agent needs an email-capable tool and a running session; installing
the server does not give every AI application native email support.

## Docker-only client setup

Clone this repository on each agent machine and install Docker with Compose v2.
No host Tailscale, Rust, Himalaya, Node.js, npm, Python, or OpenSSL installation
is needed. The AI application itself must support launching a local stdio MCP
command. Linux and macOS use the supplied POSIX shell wrappers; Windows/WSL2
has not been validated. Initial image builds need internet access.

1. Obtain an ordinary agent mailbox and its password from the server operator.
   This setup configures an existing mailbox; it never creates one implicitly.
   Choose a unique client name for this machine/mailbox:

   ```sh
   ./scripts/setup-client.sh tmail.YOUR-TAILNET.ts.net YOUR-MAILBOX YOUR-CLIENT
   ```

   Replace all placeholders with actual lowercase values. The client name accepts
   letters, digits, and hyphens. Files go in `.clients/YOUR-CLIENT/`, ignored by
   Git and Docker builds. Setup runs in a tools container, preserves existing
   configuration, and records your host UID/GID for private bind-mounted files.
2. Using an editor or authorized secret store, put **only this mailbox's password**
   in `.clients/YOUR-CLIENT/mail/password`. Put a new, non-ephemeral Tailscale
   enrollment key in `.clients/YOUR-CLIENT/tailscale_authkey`. Never put either
   secret in command arguments, MCP JSON, or chat. No administrator password or
   server blob key belongs on an agent machine. Mail configs/passwords are 0600,
   directories are 0700, and the gateway auth-key file is 0644 inside its private
   directory. Keep these permissions and the generated UID/GID.
3. Build both images and start the client gateway:

   ```sh
   docker compose --env-file .clients/YOUR-CLIENT/client.env -f compose.client.yaml build gateway mail events
   docker compose --env-file .clients/YOUR-CLIENT/client.env -f compose.client.yaml up -d gateway
   docker compose --env-file .clients/YOUR-CLIENT/client.env -f compose.client.yaml ps
   docker compose --env-file .clients/YOUR-CLIENT/client.env -f compose.client.yaml exec gateway tailscale status
   ```

   Approve the new `tmail-YOUR-CLIENT` node if your tailnet requires it. Existing
   tailnet access rules apply to **this container node**, not the host's identity.
   Optional mail-client tags or mailbox Allowed IPs must identify this new node.
   After enrollment, clear the auth-key file; persistent gateway state is reused.
   With a one-use key, enroll each new gateway with its own key.
4. Register the Docker stdio commands below with your AI application. Start a
   new session to discover the tools. Docker and the gateway must stay running.
   Build before registration; an MCP session should not perform image builds.

The separate `compose.client.yaml` starts no mail server. Its gateway runs
[Tailscale in userspace](https://tailscale.com/docs/concepts/userspace-networking)
and uses [`tailscale nc`](https://tailscale.com/docs/reference/tailscale-cli#nc)
to relay just SMTP and IMAP to the configured server. There is no TUN device,
privileged container, host Tailscale dependency, or published host port. The
bridges have only an internal Docker network, no Tailscale socket/auth key,
and only their mailbox's read-only configuration and password. Their internal
ports 1465/1993 relay to server ports 465/993; TLS ends at Stalwart and verifies
the actual ts.net hostname. DNS aliases are local routing, not a TLS bypass.

The mail image builds pinned upstream Himalaya
[`bf217e8524230dad40bce1ba0d000557c657483a`](https://github.com/pimalaya/himalaya/tree/bf217e8524230dad40bce1ba0d000557c657483a)
with locked Rust dependencies. The same image contains the locked event bridge.
Rust compilation and npm installation happen only during Docker builds. The
published Himalaya v2.2.1 binary lacks this MCP functionality.

To use Himalaya directly without installing it on the host:

```sh
docker compose --env-file .clients/YOUR-CLIENT/client.env -f compose.client.yaml run --rm -T --no-deps mail cli envelope list
```

The MCP process communicates on stdin/stdout. Keep `-T` (no pseudo-terminal),
`--rm`, and `--no-deps` in client configurations. The image enables sending and
replying but keeps `--allow-write` absent, so deletion/move tools are omitted.
MCP reads may leave messages unread; track handled Message-IDs separately.

Each additional mailbox gets its own client directory, Compose project, gateway
identity, and event state. Never share one global MCP registration between
unrelated agents. Use separate OS accounts, client profiles, or project-scoped
registrations. To stop one client stack, use the same `--env-file`/`-f` options
with `stop`. Never use `down -v` unless intentionally deleting its tailnet identity.
Back up the protected client files and event state separately from the server.
If moving to a host with a different UID/GID, update the client env and private
file ownership deliberately; do not loosen permissions or discard event state.

## Migrating an existing native bridge

Stop the old mail/event MCP processes before enabling the Docker entries. Reuse
the same mailbox password and sender allowlist; account recreation or password
rotation is unnecessary. Copy the private event-state directory into this
client's `state/inbox/` directory, preserving permissions and pending/acknowledged
records. After confirming the exact same server and mailbox, change only the
state file's `identity` port from `:993/` to `:1993/` to match the internal gateway
port. Retain UIDVALIDITY, cursor, and pending events. Keep a backup of that state;
do not erase it to bypass an identity mismatch. An active lock must be released
by stopping the old process; a crashed lock expires after about ten seconds.
Merge the Docker registrations into the existing AI client configuration,
replacing the corresponding native entries and retaining unrelated MCP servers.

## Claude Code

Register from that agent's own OS account, substituting absolute paths:

```sh
claude mcp add --transport stdio --scope user tmail -- \
  /absolute/path/to/docker compose \
  --env-file /absolute/path/tmail/.clients/YOUR-CLIENT/client.env \
  -f /absolute/path/tmail/compose.client.yaml run --rm -T --no-deps mail
claude mcp list
```

Use the actual Docker executable path (for example, `command -v docker`). Desktop
apps must have permission to use the same Docker engine/context as your shell.
Use `/mcp` in Claude Code to inspect availability. Ask it to list mail, read a
test message, and reply with the original thread headers. Tool approvals remain
subject to your Claude configuration. See the [official MCP instructions](https://code.claude.com/docs/en/mcp).

For automatic reactions in an open terminal session, also configure tmail's
[mail channel bridge](channels.md). It watches INBOX through IMAP IDLE and pushes
Claude channel events; Himalaya supplies the read/reply tools. This needs an
explicitly enabled channel, a sender allowlist, and durable event acknowledgments.
Guide this configuration after every Claude Code mailbox creation, including
later account additions. If the user chooses on-demand mail only, leave the
channel disabled.

For clients without channel support, periodic checks can use an explicitly
requested schedule or existing OS job. Keep a durable processed-ID list and a
maximum reply count. Neither Himalaya nor the channel bridge launches a closed
Claude application.

## Claude Desktop

Merge [the JSON example](../clients/claude-desktop.json.example) into Claude
Desktop's local MCP configuration. On macOS this is normally
`~/Library/Application Support/Claude/claude_desktop_config.json`. Replace every
absolute-path placeholder and restart the app. Validate read/send/reply in a
conversation. Desktop UI availability and tool approval depend on your installed
version; a local MCP process does not initiate a conversation by itself.

## Codex / ChatGPT CLI and desktop

Merge [the TOML example](../clients/codex.toml.example) into the MCP config used by
your installed OpenAI client (Codex uses `~/.codex/config.toml`, shared between its
CLI and desktop). These examples require a client that supports **local stdio**;
consult its current [MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
Do not expose this bridge over public HTTP to accommodate a cloud-only client.

Check the configured server in the client's MCP/settings UI or `codex mcp list`.
Use a fresh conversation to list, read, and reply to a synthetic owner message.
For polling, explicitly create a supported desktop automation/scheduled task
that checks this mailbox, or schedule an existing CLI job under the agent's OS
account. Confirm that the scheduled runtime has access to this local MCP config,
protected client files, Docker, and the running gateway. Include the instructions in
[agent-instructions.md](../clients/agent-instructions.md), plus your specific
authorization rules. No schedule is installed by this repository.

## Compatibility and verification

| Client | Connection | Wake-up responsibility | Verification |
|---|---|---|---|
| Standard email clients | SMTP/IMAP TLS | Client polling/IMAP IDLE | Server protocol tests automated |
| Himalaya pinned revision | CLI or local stdio MCP | Caller/scheduler | Production image and isolated Docker MCP tests |
| Claude Code terminal | Himalaya plus local `tmail-events` channel | IMAP IDLE events while an enabled session stays open | Bridge protocol tested; live Claude reaction needs a separate session test |
| Claude Desktop | Local stdio MCP | User/application scheduler if supported | Example supplied; live app session untested |
| Codex / supported ChatGPT CLI | Local stdio MCP | CLI job or supported scheduling | Example supplied; live app session untested |
| Codex / supported ChatGPT desktop | Local stdio MCP | Explicit automation where supported | Example supplied; live app session untested |
| Other local MCP clients | Standard stdio MCP | That client's runner | Not individually tested |
| Browser/cloud-only AI clients | No access to local stdio by default | Provider-specific | No universal integration claimed |

An email address and peer grant let agents exchange messages. Automatic
reasoning/replies still require an active agent runtime with an explicit mail
handling policy. The optional channel watches mail locally; the project includes
no universal agent launcher. Claude channel events are a client-specific
extension, not a guarantee that every MCP application can start an AI turn.
