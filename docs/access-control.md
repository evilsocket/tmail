# Optional Tailscale access rules

You can run tmail without learning or editing Tailscale ACLs. The basic setup
enrolls an untagged Tailscale node and uses your tailnet's existing access policy.
There is no policy-acknowledgement flag or required server tag.

ACLs (access control lists) control **which devices can connect**. Tailscale also
supports a newer rule format called **grants**; the supplied template uses that
format. These network rules are separate from tmail accounts and the directed
agent-to-agent email permissions configured in Stalwart.

With Tailscale's default allow-all policy, all devices on the tailnet can reach
tmail's three endpoints. They need mailbox credentials to read/send email and
administrator credentials to administer it, but can reach the login surfaces
and attempt to exploit the services. Restricting network access reduces that
exposure, particularly on a shared tailnet or one containing less trusted agents.
An already restricted tailnet may have different behavior. See
[Tailscale's access-control documentation](https://tailscale.com/docs/features/access-control/acls).

## What the optional template allows

A tag is a label assigned to a Tailscale device. The template uses these labels
to select the server and the devices that should be allowed to connect to it:

| Tag | Assign to | Access to tmail |
|---|---|---|
| `tag:tmail-server` | The dedicated `tmail` node created by the container | Destination for the rules |
| `tag:tmail-admin` | Devices you use to administer tmail | HTTPS 443, SMTP 465, IMAP 993 |
| `tag:tmail-client` | Approved human/agent email devices | SMTP 465 and IMAP 993 |
| Neither admin nor client | Other devices | No access, provided no other rule allows it |

## Enable the restrictions

1. Open the **Access controls** page in the Tailscale admin console. Adapt
   [config/tailscale-policy.hujson](../config/tailscale-policy.hujson) to your
   existing policy. Replace `you@example.com` with your Tailscale account identity
   and the two example test addresses with an actual unapproved node's Tailscale
   IPv4 and IPv6 addresses. Only trusted operators should own the tags.
2. **Remove or narrow broader rules that allow connections to the tmail node.**
   Tailscale rules are additive: adding restrictive rules does not override an
   existing allow-all rule. Preserve access needed by unrelated tailnet services
   when adapting the policy; do not blindly replace your entire policy file.
   Require all included allow/deny tests to pass before saving.
3. On the **Machines** page, assign the tags from the table to the corresponding
   devices. Tag the container's dedicated `tmail` node, which may be separate from
   its Docker host's own Tailscale node. You can instead use an auth key tagged
   `tag:tmail-server` when first enrolling tmail after defining the tags. No Compose
   changes are needed. See [Tailscale's tag guide](https://tailscale.com/docs/features/tags)
   for assignment and how tagged device ownership works.
4. Check the result from real devices: an administrator device can open `/admin`
   and use mail; a mail-only device can use mail but cannot reach HTTPS; an
   unapproved device cannot reach any of the three ports. Test both IPv4 and IPv6.
   Network permission does not replace the corresponding application login.

Existing deployments keep their Tailscale policy and persisted node identity.
Making this setup optional does not remove tags or broaden an existing policy.
If you later choose to remove these restrictions, update the policy and device
tags deliberately in the Tailscale console; a container restart does not do so.
