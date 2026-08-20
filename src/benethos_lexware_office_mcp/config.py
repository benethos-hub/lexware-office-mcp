"""Settings resolution and credential lookup.

Precedence, highest first: a real environment variable, a ``.env`` in the
working directory (development only), a ``.env`` in the per-user config
directory. Nothing is ever read from the directory a client happened to spawn
the process in unless that file is explicitly present, and no secret is ever
read from the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

from platformdirs import user_cache_dir, user_config_dir

from .errors import ConfigError, register_secret

__all__ = ["Mode", "Settings", "config_dir", "download_dir", "load_settings"]

APP_NAME = "benethos-lexware-office-mcp"

Mode = Literal["read", "write", "full"]
MODES: tuple[str, ...] = get_args(Mode)

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
DEFAULT_LOG_LEVEL = "INFO"


def config_dir() -> Path:
    """Per-user configuration directory for this application."""
    return Path(user_config_dir(APP_NAME, appauthor=False))


def download_dir() -> Path:
    """Default directory for downloaded documents."""
    return Path(user_cache_dir(APP_NAME, appauthor=False)) / "downloads"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Read a minimal ``.env`` file.

    Supports ``KEY=value``, ``export KEY=value``, ``#`` comments and quoted
    values. Anything else is ignored rather than raising, because a malformed
    line in a config file must not stop the server from starting.
    """
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        line = line.removeprefix("export ").lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _env_lookup(cwd: Path | None = None) -> dict[str, str]:
    """Merge the three sources into one mapping, highest precedence last."""
    merged: dict[str, str] = {}
    merged.update(_parse_env_file(config_dir() / ".env"))
    merged.update(_parse_env_file((cwd or Path.cwd()) / ".env"))
    merged.update(os.environ)
    return merged


def _as_float(raw: str | None, fallback: float, *, name: str) -> float:
    if raw is None or raw.strip() == "":
        return fallback
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}.") from None
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero, got {value}.")
    return value


def _as_int(raw: str | None, fallback: int, *, name: str, minimum: int = 1) -> int:
    if raw is None or raw.strip() == "":
        return fallback
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}.") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}.")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved configuration for one server process."""

    api_key: str | None = None
    base_url: str = DEFAULT_BASE_URL
    app_base_url: str = DEFAULT_APP_BASE_URL
    mode: Mode = "read"
    download_path: Path | None = None
    timeout: float = DEFAULT_TIMEOUT
    rate: float = DEFAULT_RATE
    burst: int = DEFAULT_BURST
    page_size: int = DEFAULT_PAGE_SIZE
    log_level: str = DEFAULT_LOG_LEVEL

    def require_api_key(self) -> str:
        """Return the API key, or explain how to supply one.

        Settings resolve without a key on purpose, so that the server starts,
        lists its tools and runs its tests without credentials. Only a call
        that actually reaches the API needs one.
        """
        if not self.api_key:
            raise ConfigError(
                "No API key. Set LXO_MCP_API_KEY, or put it in a .env file at "
                f"{config_dir() / '.env'}. Create a key in Lexware Office under "
                "Extensions, Public API."
            )
        return self.api_key


def load_settings(
    env: dict[str, str] | None = None, *, cwd: Path | None = None
) -> Settings:
    """Resolve settings from the environment.

    ``env`` is injectable so the test suite never touches the real
    environment or the user's config directory.
    """
    source = env if env is not None else _env_lookup(cwd)

    def get(name: str) -> str | None:
        value = source.get(f"LXO_MCP_{name}")
        return value.strip() if isinstance(value, str) else None

    api_key = get("API_KEY") or None
    register_secret(api_key)

    mode_raw = (get("MODE") or "read").lower()
    if mode_raw not in MODES:
        raise ConfigError(
            f"LXO_MCP_MODE must be one of {', '.join(MODES)}, got {mode_raw!r}."
        )

    log_level = (get("LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper()
    if log_level not in LOG_LEVELS:
        log_level = DEFAULT_LOG_LEVEL

    raw_download = get("DOWNLOAD_DIR")

    return Settings(
        api_key=api_key,
        base_url=(get("BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        app_base_url=(get("APP_BASE_URL") or DEFAULT_APP_BASE_URL).rstrip("/"),
        mode=mode_raw,  # type: ignore[arg-type]
        download_path=Path(raw_download) if raw_download else None,
        timeout=_as_float(get("TIMEOUT"), DEFAULT_TIMEOUT, name="LXO_MCP_TIMEOUT"),
        rate=_as_float(get("RATE"), DEFAULT_RATE, name="LXO_MCP_RATE"),
        burst=_as_int(get("BURST"), DEFAULT_BURST, name="LXO_MCP_BURST"),
        page_size=_as_int(
            get("PAGE_SIZE"), DEFAULT_PAGE_SIZE, name="LXO_MCP_PAGE_SIZE"
        ),
        log_level=log_level,
    )
