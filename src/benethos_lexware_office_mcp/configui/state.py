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
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings, env_file_in_effect, load_settings
from ..envfile import read_env_file
from ..policy import ToolPolicy
from .profiles import ProfileStore, profile_file
from .render import (
    CLI_SOURCE,
    DEFAULT_SOURCE,
    ENV_SOURCE,
    FILE_SOURCE,
    SEARCH_SOURCE,
)

__all__ = ["SETTING_KEYS", "Installation"]

# The three settings with a form of their own, named here because the
# lists below are built by leaving them out.
API_KEY = "LXO_MCP_API_KEY"
POLICY_KEY = "LXO_MCP_TOOL_POLICY"
BEARER_KEY = "LXO_MCP_BEARER_TOKEN"

# Every setting a person may see, in the order the settings sample introduces
# them. The key is first because it is the one that has to be there.
SETTING_KEYS: tuple[str, ...] = (
    "LXO_MCP_API_KEY",
    "LXO_MCP_BASE_URL",
    "LXO_MCP_APP_BASE_URL",
    "LXO_MCP_TOOL_POLICY",
    "LXO_MCP_DOWNLOAD_DIR",
    "LXO_MCP_TIMEOUT",
    "LXO_MCP_RATE",
    "LXO_MCP_BURST",
    "LXO_MCP_PAGE_SIZE",
    "LXO_MCP_PDF_PAGES",
    "LXO_MCP_LOG_LEVEL",
    "LXO_MCP_BEARER_TOKEN",
)

# Editable on the credentials page. `LXO_MCP_TOOL_POLICY` is deliberately not:
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


@dataclass
class Installation:
    """The files this interface acts on, and the settings they produce."""

    settings: Settings
    env_path: Path
    cwd: Path = field(default_factory=Path.cwd)

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

    def source_of(self, key: str) -> str:
        """Where this value comes from, in the order that decides.

        A file is asked before the command line for one reason: the policy
        path lands in the settings whether it came from ``--tools-file`` or
        from ``LXO_MCP_TOOL_POLICY`` in a file, and calling the second one
        "Aufruf" would be wrong. When nothing names it at all, the search
        found it - which is not the same as a built-in default either.
        """
        if os.environ.get(key, "").strip():
            return ENV_SOURCE
        if self.source_file(key) is not None:
            return FILE_SOURCE
        if key == POLICY_KEY:
            return (
                CLI_SOURCE
                if self.settings.tool_policy_path is not None
                else SEARCH_SOURCE
            )
        return DEFAULT_SOURCE

    def source_file(self, key: str) -> Path | None:
        """The ``.env`` that supplies this value, if a file does.

        There is only one it can be. The settings this page reports were
        loaded from ``env_path`` alone, so a key it does not carry came from
        the environment or from nowhere - never from a neighbouring file.
        """
        if self.shadowed(key):
            return None
        if read_env_file(self.env_path).get(key, "").strip():
            return self.env_path
        return None

    def source_detail(self, key: str) -> str:
        """A tooltip for the badge: which file, or which variable."""
        if self.shadowed(key):
            return f"Umgebungsvariable {key}"
        supplier = self.source_file(key)
        if supplier is not None:
            return str(supplier)
        if key == POLICY_KEY:
            if self.settings.tool_policy_path is not None:
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
