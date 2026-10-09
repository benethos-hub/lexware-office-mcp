# The image of this server, built from the repository root, which is the
# build context:
#
#   docker build -f containers/images/lexware-office-mcp/Dockerfile .
#
# Two stages, after one that only holds the uv binary. The first installs
# the locked dependencies and this package into a virtual environment, the
# second copies that environment into an image that carries no build tools,
# no lockfile and no sources.
#
# Both images it starts from are pinned by digest as well as tag. A tag is a
# pointer its publisher can move, the digest is the content itself, so a
# rebuild of the same commit gets the same bytes. The tag stays for the
# reader and for Dependabot, which raises the digest when the tag moves.
#
# Dependabot reads FROM lines only. An image named inside `COPY --from=` is
# invisible to it, which is why uv has a stage of its own: written inline,
# it never got a pull request. It names the exact release, so each one
# arrives as a new tag rather than as a digest moving under the same one.
#
# There is no `# syntax=` line on purpose. It pulls a frontend image by a
# moving tag on every build, the one pull the pins would not cover, and
# nothing here needs more than the frontend built into BuildKit.

# ---- uv: only the source of the binary -------------------------------------
FROM ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a AS uv

# ---- builder ---------------------------------------------------------------
FROM python:3.14-slim@sha256:f85c5697265c178cc6887276c55fe16cf3d14ca35c3df6a5eab3b360534a55d2 AS builder

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Dependencies first, from the lockfile and without the project itself: this
# layer is rebuilt only when pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

# Then the project, as a real wheel rather than an editable install, so
# /opt/venv is self-contained and can simply be copied.
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime ---------------------------------------------------------------
FROM python:3.14-slim@sha256:f85c5697265c178cc6887276c55fe16cf3d14ca35c3df6a5eab3b360534a55d2 AS runtime

# **Why this binds 0.0.0.0.** A process on the container's own loopback cannot
# be reached through a published port at all - Docker forwards to the
# container's address, not to its loopback. The isolation is the network
# namespace, and who may reach the port is decided on the host side by the
# publish: compose maps 127.0.0.1 only.
#
# /downloads is named here, and a directory named by LXO_MCP_DOWNLOAD_DIR is
# cleaned only when LXO_MCP_KEPT_DOWNLOADS says so as well, since outside a
# container it may be somebody's own folder. This one is the container's, so
# it keeps the newest 100 downloads like the default cache directory does.
# Being an image variable, it beats /config/.env: change it in compose.yaml
# or with `docker run -e`, not in the configuration interface.
#
# **The bearer token is not baked in, and must not be.** A secret in an image
# is shared by everyone who pulls it. The server makes one on first start
# instead - thirty-two random bytes, written into /config/.env, which is a
# volume and therefore this installation's own. The configuration interface
# shows it, because it has to be copied into a client to be of any use.
#
# The API key is not baked in either. It belongs in /config/.env, which the
# configuration interface writes - see the `setup` profile in compose.yaml.
#
# The build warns `SecretsUsedInArgOrEnv` about LXO_MCP_GENERATE_BEARER_TOKEN.
# That rule matches the name, and the value here is 1: it asks the server to
# make a token, it is not one. The warning stays rather than being switched
# off, because the rule would then also stop watching for the mistake it is
# meant to catch - an actual key written into this file.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    LXO_MCP_TRANSPORT=streamable-http \
    LXO_MCP_HTTP_HOST=0.0.0.0 \
    LXO_MCP_HTTP_PORT=8770 \
    LXO_MCP_HTTP_PATH=/mcp \
    LXO_MCP_TOOL_POLICY=/config/tools.json \
    LXO_MCP_DOWNLOAD_DIR=/downloads \
    LXO_MCP_KEPT_DOWNLOADS=100 \
    LXO_MCP_EXIT_ON_CONFIG_CHANGE=1 \
    LXO_MCP_GENERATE_BEARER_TOKEN=1

# A non-root user that owns what it writes.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /config /downloads \
    && chown appuser:appuser /config /downloads

COPY --from=builder /opt/venv /opt/venv

USER appuser

# The settings file is searched relative to the working directory as well, so
# this is what makes /config/.env the one in effect without naming a path
# anywhere. It is created empty because the search has to find a file, not a
# promise: a fresh named volume inherits it from the image.
WORKDIR /config
RUN touch /config/.env

EXPOSE 8770

# /config holds the .env, the policy file and the saved profiles. /downloads
# holds the newest documents fetched from the API, real business records.
VOLUME ["/config", "/downloads"]

# Liveness only: the port answers. Not the MCP endpoint, which would need the
# bearer token, and a health check is not a place to put a secret.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, socket; socket.create_connection(('127.0.0.1', int(os.environ.get('LXO_MCP_HTTP_PORT', '8770'))), 3).close()" || exit 1

ENTRYPOINT ["benethos-lexware-office-mcp"]
