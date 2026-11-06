# Mail events in Claude Code

tmail includes a local channel bridge at `clients/channel/server.mjs`. It watches
one agent's INBOX using IMAP IDLE and emits `notifications/claude/channel` over
stdio when new mail arrives from an allowed sender. An open Claude Code terminal
session can react without `/loop` or a scheduled prompt. Himalaya remains the
separate `tmail` MCP server for reading and replying.

The bridge runs in an on-demand Docker container on the agent's machine. It
opens no listening ports and needs no webhooks. Its client gateway provides
Tailscale connectivity; the server's three services stay unchanged. Dependencies
are locked in `clients/channel/package-lock.json` and installed inside the image.

## Configure the event container

1. Complete [Docker-only client setup](clients.md) for this mailbox. This builds
   the image for both mail tools and events. Do not install Node or npm on the
   host, and do not start the events service detached: its stdio must belong to
   the AI session that receives notifications.
2. Setup generates `.clients/YOUR-CLIENT/mail/channel.json` with the same mailbox
   and a read-only `/config/password` mount. The channel stores its cursor,
   pending events, and lock under `.clients/YOUR-CLIENT/state/`, mounted at `/state`.
   Its `stateDirectory` is `/state/inbox`, so both the directory and its sibling
   `inbox.lock` stay inside the writable mount.
   Keep the files 0600 and directories 0700. These are container paths; do not
   replace them with host paths. No host Keychain command is invoked from inside
   Docker. Export an authorized mailbox secret into the protected password file
   if your organization uses a host secret manager. Never mount a whole keychain
   or put passwords into environment variables or MCP arguments.

3. Set `allowedSenders` to the exact local addresses permitted to wake this agent.
   The template allows **only `owner@tmail.internal`**. Add another agent only
   when the user requests that interaction, and install the necessary directed
   mail-server grants too. The channel allowlist and server peer grants are
   independent: both must allow a peer. An empty array disables all wake-ups.
   Self-mail and messages without exactly one matching From address never wake
   the session. Display names have no effect on this check.

4. Register a second MCP server, retaining the existing `tmail` entry:

   ```sh
   claude mcp add --transport stdio --scope user tmail-events -- \
     /absolute/path/to/docker compose \
     --env-file /absolute/path/tmail/.clients/YOUR-CLIENT/client.env \
     -f /absolute/path/tmail/compose.client.yaml run --rm -T --no-deps events
   ```

   Substitute the result of `command -v docker` for the Docker path. Keep this
   checkout at the configured absolute path and start the gateway beforehand.
   The session starts/removes its event container; state survives in the bind
   mount. For an agent-specific project
   config use `--scope project`; do not register multiple mailboxes globally
   under the same server name. Preserve all unrelated client configuration.

5. Start a new **interactive Claude Code terminal session** with:

   ```sh
   claude --dangerously-load-development-channels server:tmail-events
   ```

   Custom channels currently require this research-preview flag and its
   interactive confirmation. It bypasses the channel-plugin allowlist for this
   named entry; it does **not** bypass tool permissions or organization policy.
   Do not substitute `--dangerously-skip-permissions`. Team/Enterprise policy
   may require an administrator to enable channels. This development-channel
   flag does not work with `claude -p` or the Agent SDK.

   Run `/mcp` and check both `tmail` and `tmail-events`. Include
   [agent-instructions.md](../clients/agent-instructions.md) in that agent's
   operating instructions, then ask it to call `channel_status`. Wait for
   `connected: true` before testing arrivals. Keep the terminal session open;
   this bridge does not launch Claude or wake a sleeping computer.

The Claude-specific contract and enablement requirements are documented in
[Channels](https://code.claude.com/docs/en/channels) and the
[Channels reference](https://code.claude.com/docs/en/channels-reference).
Other MCP clients can continue using Himalaya. Do not assume that Claude Desktop,
IDE panels, or other vendors implement Claude Code's event handling.

## Delivery and acknowledgment

- **First connection:** existing messages are left for an explicit inbox check.
  The initial UID cursor starts at the current end of INBOX, so installing a
  channel does not automatically process mail history.
- **Subsequent starts/reconnects:** messages delivered since that cursor are
  scanned, including mail received while the bridge was stopped. Stalwart's IDLE
  events trigger immediate checks while connected; no AI polling schedule is
  needed. A quiet IMAP reconciliation every 30 seconds also catches a missed
  push or an arrival racing with reconnection; it invokes no model for an empty
  inbox. Network failures retry with bounded backoff and full TLS verification.
- **Minimal events:** notifications carry an event ID, IMAP UID, mailbox name,
  and allowlisted sender. No subject, message body, attachment, or credential is
  included. The agent uses Himalaya to inspect mail under its own instructions.
  An IMAP UID is not necessarily a Himalaya tool ID; list envelopes to resolve
  the message rather than blindly passing the UID to `message_read`.
- **Acknowledge work:** after handling or deliberately skipping an event, the
  agent calls `channel_ack` with its `event_id`. This only updates local channel
  state; it does not mark mail read or delete anything. `channel_status` lists
  pending events so a missed notification can be recovered explicitly.
- **Replay:** pending events are saved before emission and replayed on bridge
  restart until acknowledged. They are emitted once per bridge process, not on
  a repeated timer. Delivery is at least once; record processed Message-IDs and
  sent replies before acknowledgment to avoid duplicate work. A crash between
  sending a reply and recording it can still require manual reconciliation.
- **Backpressure:** at most 100 notifications remain pending. When full, scanning
  pauses and resumes as events are acknowledged; remaining mail stays on the
  server. The bridge never interprets an MCP write as proof that Claude acted.
  A session that has not enabled the channel can silently ignore notifications.

The allowlist permits notification delivery, not arbitrary emailed commands.
Keep explicit reply policies and a bounded number of replies per conversation.
Automatic reactions may send email content to the model provider and consume
model usage. No schedule, automatic sender grant, or tool-permission bypass is
installed by this bridge.

## Troubleshooting and recovery

Ask the agent to call `channel_status` to distinguish connected, pending, and
failed states. Logs go only to stderr with generic errors; IMAP protocol logs
and message content are disabled.

- **Connected but no automatic response:** check the startup channel flag,
  interactive confirmation, organization policy, sender allowlist, and server
  peer grants. Check whether this is old mail predating the first connection.
  `claude mcp list` alone proves neither channel enablement nor an AI reaction.
- **Connection failure:** verify Tailscale connectivity, the exact TLS hostname,
  and the agent's password source. Credentials are read again on reconnect.
  Restart the session after editing config, allowlists, or password files.
- **Startup failure:** check the image build, gateway health, private file modes,
  configured UID/GID, and absolute paths. One process can use a state directory at a time. After a crash,
  its lock becomes stale after about ten seconds; retry then. Keep one channel
  consumer per mailbox on a node to avoid duplicate agents handling the same mail.
- **`uidvalidity_changed`:** the mailbox was recreated or restored with a new
  UID generation. The watcher stops automatic delivery and preserves old state.
  Stop the session, reconcile pending work and mail history manually, archive
  the old private state directory, then start with a new one. Its initial cursor
  skips existing history. Do not erase state as a generic connection workaround.
- **Removing a sender:** update `allowedSenders`, restart the bridge, and revoke
  its mail-server grants if desired. Pending events from that sender are dropped
  on restart; events already delivered to an open conversation cannot be recalled.

For a live acceptance test, explicitly authorize a synthetic owner-to-agent
message, leave the enabled session idle, and then send it. Observe an unsolicited
channel event followed by Claude's read/reply actions and acknowledgment. Test
the threaded reply separately. A scripted MCP round trip proves the bridge and
mail path, not that the installed Claude UI actually reacted.

## Tests

```sh
./tests/channel.sh
```

This command runs unit checks inside Docker, builds a disposable Docker test target and uses synthetic
mail, a private test CA, and tmpfs storage with no network or host ports. It
does not read the deployment's `.env`, credentials, or mail volumes. Node is
included in the client and test images, never in the mail-server services.
