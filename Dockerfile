# Two stages. The first installs the locked dependencies and this package into
# a virtual environment, the second copies that environment into an image that
# carries no build tools, no lockfile and no sources.
#
# Both images it starts from are pinned by digest as well as tag. A tag is a
# pointer its publisher can move, the digest is the content itself, so a
# rebuild of the same commit gets the same bytes. The tag stays for the
# reader and for Dependabot, which raises the digest when the tag moves.
#
# There is no `# syntax=` line on purpose. It pulls a frontend image by a
# moving tag on every build, the one pull the pins would not cover, and
# nothing here needs more than the frontend built into BuildKit.

# ---- builder ---------------------------------------------------------------
FROM python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS builder

# The uv binary from its own image.
COPY --from=ghcr.io/astral-sh/uv:0.12@sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 /uv /usr/local/bin/uv

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
FROM python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS runtime

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
