"""Settings resolution and credential lookup.

Precedence, highest first:

1. a real environment variable
2. ``.env`` in the working directory
3. ``config/.env`` below the working directory
4. ``config/.env`` of the source checkout this package runs from
5. ``.env`` in the per-user config directory

Rule 4 is what makes a clone usable no matter where it is started from, which
matters because a client such as Claude Desktop spawns the server with a
working directory of its own. It applies **only to a source checkout**, and
:func:`_project_config_dir` decides that by looking for a ``pyproject.toml``. A
package installed from a wheel sits in ``site-packages``, which has no
``pyproject.toml``, so nothing is read from there — reading configuration out
of a shared install directory is not a property this server should have.

The invocation beats the installation, so 2 and 3 sit above 4.

``config/.env.sample`` documents every setting and is the file to copy. No
secret is ever read from a versioned file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

from platformdirs import user_cache_dir, user_config_dir

from .errors import ConfigError, register_secret

__all__ = [
    "DEFAULT_PDF_PAGES",
    "MAX_PAGE_SIZE",
    "Mode",
    "Settings",
    "config_dir",
    "download_dir",
    "load_settings",
]

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

DEFAULT_LOG_LEVEL = "INFO"

# The per-tool policy lives beside the .env rather than in the repository: it
# says what this installation is allowed to do, which is a property of the
# machine and the account, not of the code.
TOOL_POLICY_NAME = "tools.json"


def config_dir() -> Path:
    """Per-user configuration directory for this application."""
    return Path(user_config_dir(APP_NAME, appauthor=False))


def tool_policy_file() -> Path:
    """The per-tool policy file this installation uses.

    The same search as the ``.env``, so the two are found the same way and a
    checkout can override an installed configuration for both.
    """
    return resolve_config_file(TOOL_POLICY_NAME)


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


def _project_config_dir() -> Path | None:
    """``config/`` of the source checkout, or ``None`` when installed.

    The package lives at ``<root>/src/<package>/``, so the root is two levels
    up. A ``pyproject.toml`` there is what distinguishes a checkout from a
    wheel unpacked into ``site-packages``, where that path would point at a
    directory shared with every other installed package.
    """
    root = Path(__file__).resolve().parents[2]
    return root / "config" if (root / "pyproject.toml").is_file() else None


def config_candidates(name: str, cwd: Path | None = None) -> list[Path]:
    """Every place a configuration file called ``name`` may live.

    Ordered by precedence, **lowest first**, so a later entry wins:

    1. the per-user configuration directory, which is what an installed copy
       uses and the only one that exists on a machine without the sources
    2. ``config/`` of the checkout, so working on the code overrides the
       installed configuration rather than fighting it
    3. ``config/`` and then the root of the current working directory, for
       running against a different account without editing anything

    One order for every configuration file there is. The ``.env`` merges its
    candidates key by key, the policy file takes the last one that exists, but
    both look in the same places in the same sequence — which is the part a
    person has to keep in their head.
    """
    here = cwd or Path.cwd()
    found = [config_dir() / name]
    project = _project_config_dir()
    if project is not None:
        found.append(project / name)
    found.append(here / "config" / name)
    found.append(here / name)
    return found


def resolve_config_file(name: str, cwd: Path | None = None) -> Path:
    """The configuration file called ``name`` that actually applies.

    The highest-precedence candidate that exists. When none does, the
    per-user directory — the place to create one, and the answer a message
    should name when a file is missing.
    """
    candidates = config_candidates(name, cwd)
    for path in reversed(candidates):
        if path.is_file():
            return path
    return candidates[0]


def _env_lookup(cwd: Path | None = None) -> dict[str, str]:
    """Merge every source into one mapping, highest precedence last."""
    merged: dict[str, str] = {}
    for path in config_candidates(".env", cwd):
        merged.update(_parse_env_file(path))
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


def _as_int(
    raw: str | None,
    fallback: int,
    *,
    name: str,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    if raw is None or raw.strip() == "":
        return fallback
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}.") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}.")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be at most {maximum}, got {value}.")
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
    pdf_pages: int = DEFAULT_PDF_PAGES
    log_level: str = DEFAULT_LOG_LEVEL
    tool_policy_path: Path | None = None

    def policy_file(self) -> Path:
        """Where this process reads and writes its per-tool policy."""
        return self.tool_policy_path or tool_policy_file()

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
            get("PAGE_SIZE"),
            DEFAULT_PAGE_SIZE,
            name="LXO_MCP_PAGE_SIZE",
            maximum=MAX_PAGE_SIZE,
        ),
        pdf_pages=_as_int(
            get("PDF_PAGES"), DEFAULT_PDF_PAGES, name="LXO_MCP_PDF_PAGES"
        ),
        tool_policy_path=(
            Path(policy_raw).expanduser()
            if (policy_raw := get("TOOL_POLICY"))
            else None
        ),
        log_level=log_level,
    )
