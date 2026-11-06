# Upstream choices and pins

The implementation uses existing open-source components, after comparing:

| Project | Fit |
|---|---|
| [Stalwart](https://github.com/stalwartlabs/stalwart) | One server with SMTP/IMAP, native policy language, and WebUI account administration |
| [Mailu](https://mailu.io/2024.06/configuration.html) | Web administration available; larger multi-service deployment |
| [docker-mailserver](https://github.com/docker-mailserver/docker-mailserver) | Established mail container; primarily CLI account administration |

The repository supplies deployment configuration and lifecycle scripts around
Stalwart and Tailscale. It does not replace their protocol implementations.

| Dependency | Pin |
|---|---|
| Stalwart Community | `v1.0.3`, OCI index digest `73c684a84c24f5b4206ec266a8deb8986fe44a9f623997e07f084388d943c8bd` |
| Tailscale | `v1.104.1`, OCI index digest `87c55d6be56ad85b3d8bceca5f87f73de288c609131460dd1be1874c250cc41d` |
| Stalwart CLI | `v1.0.14`, separate verified SHA-256 for arm64/x86_64 in Dockerfile |
| Stalwart WebUI | `v2.0.5`, SHA-256 `152a63f34bb2f470c32fe9c68f97e395994c761303364b392a2ce419b2f06162` |
| Himalaya, optional MCP | Git revision `bf217e8524230dad40bce1ba0d000557c657483a`, locked dependency build |
| Optional local channel | `@modelcontextprotocol/sdk` 1.32.2, `imapflow` 2.11.0, `proper-lockfile` 4.1.2; transitive versions/integrity in `clients/channel/package-lock.json` |

Server, client, builder, and test base images are digest-pinned. Distribution packages such as
OpenSSL and jq receive the selected distribution's security updates at build
time; builds are not claimed to be bit-for-bit reproducible. Retain the resulting
image digests when promoting a tested build.

Primary implementation references:

- [Stalwart 1.0.3 source and schema](https://github.com/stalwartlabs/stalwart/tree/v1.0.3)
- [Declarative deployments](https://stalw.art/docs/configuration/declarative-deployments/)
- [Certificate lifecycle](https://stalw.art/docs/server/tls/certificates/)
- [Local lookup administration](https://stalw.art/docs/configuration/expressions/lookup/local/)
- [Recipient-stage filtering](https://stalw.art/docs/mta/inbound/rcpt/)
- [Blob encryption](https://stalw.art/docs/storage/blob-encryption/)
- [Tailscale Docker parameters](https://tailscale.com/docs/features/containers/docker/docker-params)
- [Tailscale Serve TCP and PROXY protocol](https://tailscale.com/docs/reference/tailscale-cli/serve)
- [Private Docker service access](https://tailscale.com/docs/solutions/host-private-server-docker)
- [Claude Code channel contract](https://code.claude.com/docs/en/channels-reference)
- [ImapFlow IDLE and client API](https://imapflow.com/docs/api/imapflow-client/)

Stalwart's server is AGPL-3.0 with an alternative commercial license; this project
uses its Community functionality. Tailscale's client and the bundled CLI/WebUI
retain their upstream licenses. Himalaya is MIT OR Apache-2.0. Review upstream
license files when redistributing built images or binaries. The pinned upstream
source revisions provide the corresponding unmodified source locations.
