"""Where configuration lives: the directories, the search, the one file.

**One file applies, never several.** For the ``.env`` and for the policy file
alike, the search below picks one, and the files it did not pick are not
read. A real environment variable is a different layer and still wins over
whatever that file says.

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

The settings sample ships inside the package, so an installed copy documents
its own settings. :func:`settings_sample` reads it, and ``--settings-sample``
prints it. No secret is ever read from a versioned file.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir

from ..errors import ConfigError

__all__ = [
    "TOOL_POLICY_NAME",
    "config_candidates",
    "config_dir",
    "download_dir",
    "env_file_in_effect",
    "resolve_config_file",
    "settings_sample",
    "tool_policy_file",
]

APP_NAME = "benethos-lexware-office-mcp"

# The package the sample ships in, the top of this one.
_PACKAGE = __name__.split(".")[0]

# The per-tool policy lives beside the .env rather than in the repository: it
# says what this installation is allowed to do, which is a property of the
# machine and the account, not of the code.
TOOL_POLICY_NAME = "tools.json"

# The sample lives in the package rather than beside it, so that a wheel
# carries its own documentation of the settings. A file outside the package
# directory is not installed, which is how the ten settings once existed only
# in the README.
SAMPLE_NAME = "env.sample"


def settings_sample() -> str:
    """The commented sample listing every setting, as shipped."""
    return (resources.files(_PACKAGE) / SAMPLE_NAME).read_text(encoding="utf-8")


# platformdirs raises when no home directory resolves - HOME unset or empty and
# no password database entry for the uid. Before 4.12 it answered a relative
# ``~/.config/...`` instead, which landed below whatever the working directory
# happened to be. Neither message names a path, only what to set.
NO_HOME_CONFIG = (
    "No home directory resolves, so there is no per-user configuration "
    "directory. Set HOME, or name the files with --env-file and --tools-file."
)
NO_HOME_DOWNLOADS = (
    "No home directory resolves, so there is no default download directory. "
    "Set LXO_MCP_DOWNLOAD_DIR, or HOME."
)


def config_dir() -> Path:
    """Per-user configuration directory for this application."""
    try:
        return Path(user_config_dir(APP_NAME, appauthor=False))
    except RuntimeError:
        raise ConfigError(NO_HOME_CONFIG) from None


def tool_policy_file() -> Path:
    """The per-tool policy file this installation uses.

    The same search as the ``.env``, so the two are found the same way and a
    checkout can override an installed configuration for both.
    """
    return resolve_config_file(TOOL_POLICY_NAME)


def download_dir() -> Path:
    """Default directory for downloaded documents."""
    try:
        return Path(user_cache_dir(APP_NAME, appauthor=False)) / "downloads"
    except RuntimeError:
        raise ConfigError(NO_HOME_DOWNLOADS) from None


def _project_config_dir() -> Path | None:
    """``config/`` of the source checkout, or ``None`` when installed.

    This module lives at ``<root>/src/<package>/settings/``, so the root is
    three levels up. A ``pyproject.toml`` there is what distinguishes a checkout from a
    wheel unpacked into ``site-packages``, where that path would point at a
    directory shared with every other installed package.
    """
    root = Path(__file__).resolve().parents[3]
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

    One order for every configuration file there is, and one rule at the end
    of it: the highest-precedence candidate that exists is the file, and the
    ones below it are not consulted. Neither the ``.env`` nor the policy file
    combines with anything — which is the part a person has to keep in their
    head, and the reason it fits in a sentence.
    """
    here = cwd or Path.cwd()
    # Without a home there is no per-user directory, and the other places
    # still count: a checkout or a working directory needs none.
    try:
        found = [config_dir() / name]
    except ConfigError:
        found = []
    project = _project_config_dir()
    if project is not None:
        found.append(project / name)
    found.append(here / "config" / name)
    found.append(here / name)
    return found


def resolve_config_file(name: str, cwd: Path | None = None) -> Path:
    """The configuration file called ``name`` that actually applies.

    The highest-precedence candidate that exists, and the only one read. When
    none does, the per-user directory — the place to create one, and the
    answer a message should name when a file is missing. Without a home there
    is no such place, and :class:`ConfigError` says what to set instead.
    """
    candidates = config_candidates(name, cwd)
    for path in reversed(candidates):
        if path.is_file():
            return path
    config_dir()  # raises when there is no home, and so nowhere to create one
    return candidates[0]


def env_file_in_effect(
    cwd: Path | None = None, named: Path | None = None
) -> Path | None:
    """The one ``.env`` a process started this way reads, if there is one.

    ``named`` is a file somebody pointed at, so it is that file and the search
    does not happen. Otherwise the highest-precedence candidate that exists.
    ``None`` when no file exists at all, which is not an error: the settings
    can come entirely from the environment.
    """
    if named is not None:
        return named
    try:
        found = resolve_config_file(".env", cwd)
    except ConfigError:
        return None
    return found if found.is_file() else None
