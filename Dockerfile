# syntax=docker/dockerfile:1
FROM tailscale/tailscale:v1.104.1@sha256:87c55d6be56ad85b3d8bceca5f87f73de288c609131460dd1be1874c250cc41d AS tailscale-upstream
FROM alpine:3.22.2@sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412 AS tools
RUN apk add --no-cache openssl jq age
COPY --chmod=755 scripts /opt/tmail/scripts
COPY .env.example /opt/tmail/server.env.example
WORKDIR /workspace

# Test controller only: Docker CLI talks to a disposable test project.
FROM tools AS test-client-driver
RUN apk add --no-cache python3 docker-cli docker-cli-compose
ENTRYPOINT ["python3", "/tests/client-docker.py"]

FROM tailscale-upstream AS client-gateway
RUN apk add --no-cache socat
COPY --chmod=755 scripts/client-gateway.sh scripts/client-connect.sh /opt/tmail/
ENTRYPOINT ["/opt/tmail/client-gateway.sh"]

FROM alpine:3.22.2@sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412 AS downloads
RUN apk add --no-cache ca-certificates curl xz
ARG TARGETARCH
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) arch=x86_64; sha=c90824fe60b29d56c5a590baf321a30d422153f7aa64ac5f840d16f30895e59c ;; \
      arm64) arch=aarch64; sha=bf641b7c5176b327d21465b55ee8b269e1ea874a0c81d27d259e2e723f9e55b4 ;; \
      *) exit 1 ;; \
    esac; \
    curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
      "https://github.com/stalwartlabs/cli/releases/download/v1.0.14/stalwart-cli-${arch}-unknown-linux-musl.tar.xz" -o /cli.tar.xz; \
    echo "$sha  /cli.tar.xz" | sha256sum -c -; \
    mkdir /cli; tar -xJf /cli.tar.xz -C /cli --strip-components=1; \
    curl --fail --location --proto '=https' --tlsv1.2 --retry 3 \
      https://github.com/stalwartlabs/webui/releases/download/v2.0.5/webui.zip -o /webui.zip; \
    echo '152a63f34bb2f470c32fe9c68f97e395994c761303364b392a2ce419b2f06162  /webui.zip' | sha256sum -c -

FROM tailscale-upstream AS tailscale
COPY --chmod=755 scripts/tailscale-entrypoint.sh /usr/local/bin/tmail-tailscale
ENTRYPOINT ["/usr/local/bin/tmail-tailscale"]

FROM stalwartlabs/stalwart:v1.0.3@sha256:73c684a84c24f5b4206ec266a8deb8986fe44a9f623997e07f084388d943c8bd AS runtime
USER root
RUN apt-get update && apt-get install -y --no-install-recommends jq openssl \
    && rm -rf /var/lib/apt/lists/* \
    && setcap -r /usr/local/bin/stalwart \
    && mkdir -p /opt/tmail /run/tmail /var/cache/tmail \
    && chown 2000:2000 /run/tmail /var/cache/tmail
COPY --from=downloads /cli/stalwart-cli /usr/local/bin/stalwart-cli
COPY --from=downloads /webui.zip /opt/tmail/webui.zip
COPY config /opt/tmail/config
COPY --chmod=755 scripts /opt/tmail/scripts
ENV XDG_CACHE_HOME=/var/cache/tmail NO_COLOR=1

FROM runtime AS maintenance
COPY --from=tailscale-upstream /usr/local/bin/tailscale /usr/local/bin/tailscale
ENTRYPOINT ["/opt/tmail/scripts/maintenance.sh"]
CMD []

FROM runtime AS mail
USER 2000:2000
ENTRYPOINT ["/opt/tmail/scripts/mail-entrypoint.sh"]
CMD []

# Python stays in isolated test images, never production services.
FROM mail AS test
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
USER 2000:2000
ENTRYPOINT ["python3", "/tests/integration.py"]
CMD []

# Optional, pinned upstream MCP bridge; never part of a server service.
FROM rust:1.92.0-slim-bookworm@sha256:f1f73538ebe623fd3673a35aff3df358ae1084c64c55646516e5b17b321b6c9b AS himalaya-build
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN git init && git remote add origin https://github.com/pimalaya/himalaya.git \
    && git fetch --depth 1 origin bf217e8524230dad40bce1ba0d000557c657483a \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = bf217e8524230dad40bce1ba0d000557c657483a
RUN cargo build --locked --no-default-features --features imap,smtp,rustls-ring

FROM test AS test-mcp
COPY --from=himalaya-build /build/target/debug/himalaya /usr/local/bin/himalaya

# Client dependencies; Node and npm packages never enter the mail services.
FROM node:22.17.0-bookworm-slim@sha256:b04ce4ae4e95b522112c2e5c52f781471a5cbc3b594527bcddedee9bc48c03a0 AS channel-deps
WORKDIR /channel
COPY clients/channel/package*.json ./
RUN npm ci --ignore-scripts --no-fund --no-audit
COPY clients/channel ./

FROM channel-deps AS client
USER root
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=himalaya-build /build/target/debug/himalaya /usr/local/bin/himalaya
COPY --chmod=755 scripts/client-entrypoint.sh /opt/tmail/client-entrypoint.sh
ENV HOME=/tmp XDG_CACHE_HOME=/tmp/cache NO_COLOR=1
USER 1000:1000
ENTRYPOINT ["/opt/tmail/client-entrypoint.sh"]
CMD ["mail"]

FROM test AS test-channel
COPY --from=channel-deps /usr/local/bin/node /usr/local/bin/node
COPY --from=channel-deps /channel /channel
ENTRYPOINT ["python3", "/tests/channel.py"]

# A plain `docker build .` produces the mail image, too.
FROM mail AS default
