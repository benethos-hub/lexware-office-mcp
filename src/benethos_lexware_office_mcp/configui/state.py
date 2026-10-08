"""What this installation currently is, gathered in one place.

Every page asks the same questions — which file is being written, which value
won, what the permissions say — so they are answered once, here, rather than
four times with four slightly different ideas of precedence.

Read fresh rather than cached. The interface exists to change these files, and
a browser tab left open while somebody edits ``tools.json`` in an editor
should not go on showing what was true when the tab was opened.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ConfigError
from ..policy import ToolPolicy
from ..settings import Settings, load_settings
from ..settings.envfile import read_env_file
from ..settings.locations import env_file_in_effect
from .profiles import ProfileStore, profile_file

__all__ = [
    "CLI_SOURCE",
    "DEFAULT_SOURCE",
    "EDITABLE_KEYS",
    "ENV_SOURCE",
    "FILE_SOURCE",
    "LABELS",
    "SEARCH_SOURCE",
    "SETTING_KEYS",
    "Installation",
    "defaults",
    "downloads_dir",
    "resolved",
]

# The three settings with a form of their own, named here because the
# lists below are built by leaving them out.
API_KEY = "LXO_MCP_API_KEY"
POLICY_KEY = "LXO_MCP_TOOL_POLICY"
BEARER_KEY = "LXO_MCP_BEARER_TOKEN"

# Where a setting actually comes from. Showing the file alone would be
# misleading exactly when it matters most: a real environment variable
# outranks it, and that is how a client starts this server with its own
# account. See settings/locations.py for the full precedence.
ENV_SOURCE = "Umgebung"
CLI_SOURCE = "Aufruf"
# Nobody named this file: the search of section 7 found it when the process
# started, and it has been held since. Not a built-in default, which is the
# name of a file rather than a path to one.
SEARCH_SOURCE = "Suche"
FILE_SOURCE = "Datei"
DEFAULT_SOURCE = "Default"


@dataclass
class Installation:
    """The files this interface acts on, and the settings they produce."""

    settings: Settings
    env_path: Path
    cwd: Path = field(default_factory=Path.cwd)
    # Whether --tools-file named the policy file. The settings cannot say:
    # the path lands in them whichever named it, and the flag outranks the
    # variable, so the badge has to be told.
    tools_file_named: bool = False

    def __post_init__(self) -> None:
        # **Pinned once, at start**, exactly as the server pins its own: the
        # search of section 7 can answer differently the moment a file
        # appears somewhere, and a process that quietly changed which policy
        # file it obeys - or edits - is the harder thing to reason about.
        # Deleting the pinned file therefore disables everything rather than
        # promoting the next candidate, which is the safer failure.
        #
        # It also survives `reload`, which resolves only files and the
        # environment and would otherwise lose a path named on the command
        # line.
        self._policy_path = self.settings.policy_file()
        # Whether something named it, for the same reason: `reload` reads
        # files and the environment, and a --tools-file is in neither.
        self._policy_named = self.settings.tool_policy_path is not None

    @property
    def policy_path(self) -> Path:
        """The policy file this interface works on, fixed at start."""
        return self._policy_path

    @property
    def policy(self) -> ToolPolicy:
        """That file's flags, re-read on every question."""
        return ToolPolicy(self._policy_path)

    @property
    def profiles(self) -> ProfileStore:
        """The saved profiles that belong to that policy file."""
        return ProfileStore(profile_file(self._policy_path))

    def reload(self) -> None:
        """Resolve the settings again, after something was written.

        The policy file does not move with it: it was pinned at start and
        stays there for the life of the process, so saving a key cannot
        change which permissions this interface is editing.
        """
        self.settings = load_settings(env_file=self.env_path, cwd=self.cwd)

    # --- where a value comes from ------------------------------------------
    # In the order that decides: a real environment variable, then the command
    # line for the one setting it can name, then the .env, then the built-in
    # default. One .env, not several - `outranked_by` answers the case where
    # it is not the one a server would read, which is a statement about the
    # whole file rather than about a value.

    def file_env(self) -> dict[str, str]:
        """What the file this interface writes to holds right now."""
        return read_env_file(self.env_path)

    def outranked_by(self) -> Path | None:
        """A file a server would read *instead of* the one being edited.

        One ``.env`` applies and the others are not consulted, so a higher
        candidate does not shade a value here - it replaces the whole file.
        Editing then works, saves, and changes nothing about the server. The
        answer is on the overview beside the paths.

        ``None`` when this interface is already working on the file the search
        would pick, which is the ordinary case.
        """
        applies = env_file_in_effect(self.cwd)
        if applies is None or applies == self.env_path:
            return None
        return applies

    def source_of(self, key: str, env: dict[str, str] | None = None) -> str:
        """Where this value comes from, in the order that decides.

        A file is asked before the command line for one reason: the policy
        path lands in the settings whether it came from ``--tools-file`` or
        from ``LXO_MCP_TOOL_POLICY`` in a file, and calling the second one
        "Aufruf" would be wrong. When nothing names it at all, the search
        found it - which is not the same as a built-in default either.

        ``env`` is the file's content as :meth:`file_env` read it, for a page
        that asks about every setting in one go and wants the file read once
        rather than once per row. Left out, the file is read here.

        ``--tools-file`` is asked first of all for the policy file, because it
        outranks the environment: with both set, the path is the flag's.
        """
        if key == POLICY_KEY and self.tools_file_named:
            return CLI_SOURCE
        if os.environ.get(key, "").strip():
            return ENV_SOURCE
        if self.source_file(key, env) is not None:
            return FILE_SOURCE
        if key == POLICY_KEY:
            return CLI_SOURCE if self._policy_named else SEARCH_SOURCE
        return DEFAULT_SOURCE

    def source_file(self, key: str, env: dict[str, str] | None = None) -> Path | None:
        """The ``.env`` that supplies this value, if a file does.

        There is only one it can be. The settings this page reports were
        loaded from ``env_path`` alone, so a key it does not carry came from
        the environment or from nowhere - never from a neighbouring file.
        """
        if self.shadowed(key):
            return None
        if env is None:
            env = self.file_env()
        if env.get(key, "").strip():
            return self.env_path
        return None

    def source_detail(self, key: str, env: dict[str, str] | None = None) -> str:
        """A tooltip for the badge: which file, or which variable."""
        if key == POLICY_KEY and self.tools_file_named:
            return "Mit --tools-file auf der Kommandozeile benannt."
        if self.shadowed(key):
            return f"Umgebungsvariable {key}"
        supplier = self.source_file(key, env)
        if supplier is not None:
            return str(supplier)
        if key == POLICY_KEY:
            if self._policy_named:
                return "Mit --tools-file auf der Kommandozeile benannt."
            return "Beim Start gesucht und seitdem festgehalten."
        return ""

    def shadowed(self, key: str) -> bool:
        """Whether writing this key here would have no effect.

        True when a real environment variable sets it, which outranks every
        file. Worth saying before somebody types a value into a form and
        wonders why the server ignores it.
        """
        return bool(os.environ.get(key, "").strip())

    def has_api_key(self) -> bool:
        return bool(self.settings.api_key)


def downloads_dir(settings: Settings, unresolved: str | None = None) -> str:
    """The download directory, or why there is none.

    Without a home and without ``LXO_MCP_DOWNLOAD_DIR`` nothing resolves, and
    the page says so in the server's own words rather than failing to render.
    """
    try:
        return str(settings.download_directory())
    except ConfigError as exc:
        return str(exc) if unresolved is None else unresolved


@dataclass(frozen=True, slots=True)
class Shown:
    """One setting as the pages show it.

    The key, the label a person reads beside it, and how a value in effect
    reads - not what a file says, but what the process resolved. A setting
    added to the server is added here once, and the table, the labels and
    the placeholders follow. ``show`` is ``None`` for the policy file, which
    the installation pinned at start rather than the settings naming it.
    """

    key: str
    label: str
    show: Callable[[Settings], str] | None


def _state(value: object) -> str:
    """A secret is shown as a state, never as a value.

    The overview is the page somebody screenshots. The credentials page
    shows the bearer token itself, where it exists to be copied.
    """
    return "gesetzt" if value else "nicht gesetzt"


# Every setting a person may see, in the order the settings sample introduces
# them. The key is first because it is the one that has to be there.
SHOWN: tuple[Shown, ...] = (
    Shown(API_KEY, "API-Schlüssel", lambda s: _state(s.api_key)),
    Shown("LXO_MCP_BASE_URL", "API-Adresse", lambda s: s.base_url),
    Shown(
        "LXO_MCP_APP_BASE_URL",
        "Web-App für Deeplinks",
        lambda s: s.app_base_url,
    ),
    Shown(POLICY_KEY, "Rechtedatei", None),
    Shown("LXO_MCP_DOWNLOAD_DIR", "Downloads", lambda s: downloads_dir(s)),
    Shown(
        "LXO_MCP_KEPT_DOWNLOADS",
        "Downloads im Cache (die neuesten)",
        lambda s: str(s.downloads_kept() or "alle"),
    ),
    Shown(
        "LXO_MCP_UPLOAD_DIR",
        "Uploads nur aus",
        lambda s: str(s.upload_path) if s.upload_path else "überall",
    ),
    Shown(
        "LXO_MCP_TIMEOUT",
        "Zeitlimit je Anfrage (s)",
        lambda s: f"{s.timeout:g}",
    ),
    Shown("LXO_MCP_RATE", "Anfragen pro Sekunde", lambda s: f"{s.rate:g}"),
    Shown("LXO_MCP_BURST", "Burst", lambda s: str(s.burst)),
    Shown("LXO_MCP_PAGE_SIZE", "Zeilen je Seite", lambda s: str(s.page_size)),
    Shown(
        "LXO_MCP_PDF_PAGES",
        "PDF-Seiten je Ansicht",
        lambda s: str(s.pdf_pages),
    ),
    Shown("LXO_MCP_LOG_LEVEL", "Protokollstufe", lambda s: s.log_level),
    Shown(BEARER_KEY, "HTTP-Token", lambda s: _state(s.bearer_token)),
)

SETTING_KEYS: tuple[str, ...] = tuple(shown.key for shown in SHOWN)
LABELS: dict[str, str] = {shown.key: shown.label for shown in SHOWN}

# Editable on the settings page. `LXO_MCP_TOOL_POLICY` is deliberately not:
# it decides which policy file this interface is editing, and changing that
# from inside would swap the page's own subject out under it. The command line
# says which one to work on, and the overview shows which one won.
EDITABLE_KEYS: tuple[str, ...] = tuple(
    key
    for key in SETTING_KEYS
    # The key and the token have their own forms, one because it is
    # never shown back and one because it must never be blank. The
    # policy file is decided at start, see the overview page.
    if key not in (API_KEY, POLICY_KEY, BEARER_KEY)
)


def resolved(inst: Installation) -> dict[str, str]:
    """What each setting actually is in this process, not what a file says."""
    return {
        shown.key: str(inst.policy_path)
        if shown.show is None
        else shown.show(inst.settings)
        for shown in SHOWN
    }


def defaults() -> dict[str, str]:
    """What each editable setting is when nothing sets it, read the same way.

    The placeholder of an empty field, which is what leaving it empty means.
    """
    settings = Settings()
    return {
        shown.key: shown.show(settings)
        for shown in SHOWN
        if shown.key in EDITABLE_KEYS and shown.show is not None
    }
