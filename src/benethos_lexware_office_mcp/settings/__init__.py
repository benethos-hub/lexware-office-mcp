"""The settings of one server process, resolved once at startup.

Every setting is an ``LXO_MCP_`` variable, read from the one ``.env`` that
applies and then from the real environment, which has the last word. Which
file applies is ``locations``, how one value is read is ``parse``, and
reading and writing a ``.env`` itself is ``envfile``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..errors import ConfigError, register_secret
from . import locations
from .envfile import read_env_file
from .parse import as_float, as_int, csv_tuple, flag, https_url

__all__ = [
    "DEFAULT_APP_BASE_URL",
    "DEFAULT_BASE_URL",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_KEPT_DOWNLOADS",
    "DEFAULT_PDF_PAGES",
    "LOG_LEVELS",
    "LOOPBACK_NAMES",
    "MAX_PAGE_SIZE",
    "MAX_PDF_PAGES",
    "TRANSPORTS",
    "Settings",
    "load_settings",
]

LOG_LEVELS: tuple[str, ...] = (
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
)

DEFAULT_BASE_URL = "https://api.lexware.io"
DEFAULT_APP_BASE_URL = "https://app.lexware.de"

# Deliberately below the documented ceiling of 2 requests per second. The API
# documentation warns that enforcing the limit without a buffer commonly
# produces 429s once network jitter shifts the arrival times.
DEFAULT_RATE = 1.5
DEFAULT_BURST = 2
DEFAULT_TIMEOUT = 30.0
DEFAULT_PAGE_SIZE = 25
# Verified against the live API on 2026-08-20: `size=251` is rejected with
# "parameter 'size' must be equal or lower than 250". The 25 the documentation
# mentions is the upstream default, not the ceiling.
MAX_PAGE_SIZE = 250

# How many pages of a PDF `read_download` renders when the caller does not
# say. Deliberately *not* called a page size: `LXO_MCP_PAGE_SIZE` above is
# rows per page of a list, and confusing the two would be easy. A rendered
# page costs roughly two thousand tokens whatever it weighs in bytes, so ten
# is already a substantial answer. No ceiling is imposed, because unlike the
# page size there is no upstream limit to derive one from, and a caller can
# still override it per call.
DEFAULT_PDF_PAGES = 10

# The most pages one read_download renders, whatever the call asks for. At
# roughly two thousand tokens a page this is already far past any context
# worth spending, and it bounds the CPU a single call can take.
MAX_PDF_PAGES = 100

# The download directory is a cache of the newest downloads: every document is
# in Lexware Office and one API call away, so a file past the bound is fetched
# again rather than kept. The same number bounds `resources/list`, which the
# SDK sends whole. See `Settings.downloads_kept` for where it applies.
DEFAULT_KEPT_DOWNLOADS = 100

DEFAULT_LOG_LEVEL = "INFO"

# The HTTP transport. Loopback by default because a bind address is the one
# setting where a careless default is a security hole rather than an
# inconvenience. A container overrides it, and whoever changes it elsewhere is
# saying they mean to.
DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8770
# The names under which a bind reaches this machine only. Checked wherever a
# bind address or a Host header decides whether somebody else could be on
# the other end.
LOOPBACK_NAMES: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_HTTP_PATH = "/mcp"
TRANSPORTS: tuple[str, ...] = ("stdio", "streamable-http", "sse")
DEFAULT_TRANSPORT = "stdio"


def _env_lookup(
    cwd: Path | None = None, env_file: Path | None = None
) -> dict[str, str]:
    """One file, then the real environment, which has the last word.

    **The files do not combine.** The ``.env`` that applies is the one
    :func:`.locations.env_file_in_effect` picks, exactly as the policy file is one file
    rather than a merge of several, and for the same reason: a setting has to
    be traceable to the file a person edited, and a value arriving from a file
    they did not name is one they cannot see.

    The environment is a different layer and does merge over the top. A
    container passes its transport settings that way while the key lives in
    the mounted file, so the two have to be readable together.
    """
    merged: dict[str, str] = {}
    applies = locations.env_file_in_effect(cwd, env_file)
    if applies is not None:
        merged.update(read_env_file(applies))
    merged.update(os.environ)
    return merged


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved configuration for one server process."""

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    app_base_url: str = DEFAULT_APP_BASE_URL
    download_path: Path | None = None
    upload_path: Path | None = None
    timeout: float = DEFAULT_TIMEOUT
    rate: float = DEFAULT_RATE
    burst: int = DEFAULT_BURST
    page_size: int = DEFAULT_PAGE_SIZE
    pdf_pages: int = DEFAULT_PDF_PAGES
    # None when not set, which is not the same as any number: see below.
    kept_downloads: int | None = None
    log_level: str = DEFAULT_LOG_LEVEL
    tool_policy_path: Path | None = None
    transport: str = DEFAULT_TRANSPORT
    http_host: str = DEFAULT_HTTP_HOST
    http_port: int = DEFAULT_HTTP_PORT
    http_path: str = DEFAULT_HTTP_PATH
    bearer_token: str | None = None
    allowed_hosts: tuple[str, ...] = ()
    exit_on_config_change: bool = False
    generate_bearer_token: bool = False

    def downloads_kept(self) -> int | None:
        """How many downloads the directory keeps, or ``None`` for all of them.

        The cache directory of this user is cleaned by default, since that is
        what a cache directory is for. A directory named by
        ``LXO_MCP_DOWNLOAD_DIR`` may be somebody's own folder, so nothing is
        deleted there unless ``LXO_MCP_KEPT_DOWNLOADS`` says so as well. Zero
        keeps everything, anywhere.
        """
        if self.kept_downloads is not None:
            return self.kept_downloads or None
        return DEFAULT_KEPT_DOWNLOADS if self.download_path is None else None

    def downloads_listed(self) -> int:
        """How many downloads ``resources/list`` names. Always a bound."""
        return self.kept_downloads or DEFAULT_KEPT_DOWNLOADS

    def policy_file(self) -> Path:
        """Where this process reads and writes its per-tool policy."""
        return self.tool_policy_path or locations.tool_policy_file()

    def require_api_key(self) -> str:
        """Return the API key, or explain how to supply one.

        Settings resolve without a key on purpose, so that the server starts,
        lists its tools and runs its tests without credentials. Only a call
        that actually reaches the API needs one.
        """
        if not self.api_key:
            # Deliberately without the path of the .env: this message reaches
            # the client and a model's context, where a directory layout is
            # nothing anybody can act on. The command names the file on the
            # machine, which is where somebody can.
            raise ConfigError(
                "No API key configured for this server. Set LXO_MCP_API_KEY, "
                "or run `benethos-lexware-office-mcp setup` on the machine "
                "the server runs on."
            )
        return self.api_key


def load_settings(
    env: dict[str, str] | None = None,
    *,
    cwd: Path | None = None,
    env_file: Path | None = None,
) -> Settings:
    """Resolve settings from the environment.

    ``env`` is injectable so the test suite never touches the real
    environment or the user's config directory. ``env_file`` is a file named
    on the command line, read after the search and before the environment.
    """
    source = env if env is not None else _env_lookup(cwd, env_file)

    def get(name: str) -> str | None:
        value = source.get(f"LXO_MCP_{name}")
        return value.strip() if isinstance(value, str) else None

    api_key = get("API_KEY") or None
    register_secret(api_key)

    log_level = (get("LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper()
    if log_level not in LOG_LEVELS:
        log_level = DEFAULT_LOG_LEVEL

    raw_download = get("DOWNLOAD_DIR")

    transport = (get("TRANSPORT") or DEFAULT_TRANSPORT).lower()
    if transport not in TRANSPORTS:
        transport = DEFAULT_TRANSPORT

    bearer_token = get("BEARER_TOKEN") or None
    register_secret(bearer_token)

    # Only something that restarts the process may ask for this, so it is
    # off unless said otherwise. The container image says otherwise.
    exit_on_change = flag(get("EXIT_ON_CONFIG_CHANGE"))
    generate_token = flag(get("GENERATE_BEARER_TOKEN"))

    allowed_hosts = csv_tuple(get("ALLOWED_HOSTS"))

    return Settings(
        api_key=api_key,
        base_url=https_url(get("BASE_URL"), DEFAULT_BASE_URL, name="LXO_MCP_BASE_URL"),
        app_base_url=https_url(
            get("APP_BASE_URL"), DEFAULT_APP_BASE_URL, name="LXO_MCP_APP_BASE_URL"
        ),
        download_path=Path(raw_download).expanduser() if raw_download else None,
        upload_path=(
            Path(upload_raw).expanduser() if (upload_raw := get("UPLOAD_DIR")) else None
        ),
        timeout=as_float(get("TIMEOUT"), DEFAULT_TIMEOUT, name="LXO_MCP_TIMEOUT"),
        rate=as_float(get("RATE"), DEFAULT_RATE, name="LXO_MCP_RATE"),
        burst=as_int(get("BURST"), DEFAULT_BURST, name="LXO_MCP_BURST"),
        page_size=as_int(
            get("PAGE_SIZE"),
            DEFAULT_PAGE_SIZE,
            name="LXO_MCP_PAGE_SIZE",
            maximum=MAX_PAGE_SIZE,
        ),
        pdf_pages=as_int(
            get("PDF_PAGES"),
            DEFAULT_PDF_PAGES,
            name="LXO_MCP_PDF_PAGES",
            maximum=MAX_PDF_PAGES,
        ),
        kept_downloads=(
            as_int(kept_raw, 0, name="LXO_MCP_KEPT_DOWNLOADS", minimum=0)
            if (kept_raw := get("KEPT_DOWNLOADS"))
            else None
        ),
        tool_policy_path=(
            Path(policy_raw).expanduser()
            if (policy_raw := get("TOOL_POLICY"))
            else None
        ),
        log_level=log_level,
        transport=transport,
        http_host=get("HTTP_HOST") or DEFAULT_HTTP_HOST,
        http_port=as_int(get("HTTP_PORT"), DEFAULT_HTTP_PORT, name="LXO_MCP_HTTP_PORT"),
        http_path=get("HTTP_PATH") or DEFAULT_HTTP_PATH,
        bearer_token=bearer_token,
        allowed_hosts=allowed_hosts,
        exit_on_config_change=exit_on_change,
        generate_bearer_token=generate_token,
    )
