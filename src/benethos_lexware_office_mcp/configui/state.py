"""What this installation currently is, gathered in one place.

Every page asks the same questions — which file is being written, which value
won, what the permissions say — so they are answered once, here, rather than
four times with four slightly different ideas of precedence.

Read fresh rather than cached. The interface exists to change these files, and
a browser tab left open while somebody edits ``tools.json`` in an editor
should not go on showing what was true when the tab was opened.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings, config_candidates, load_settings
from ..envfile import read_env_file
from ..policy import ToolPolicy
from .profiles import ProfileStore, profile_file
from .render import (
    CLI_SOURCE,
    DEFAULT_SOURCE,
    ENV_SOURCE,
    FILE_SOURCE,
    OTHER_FILE_SOURCE,
)

__all__ = ["SETTING_KEYS", "Installation"]

# Every setting a person may see, in the order config/.env.sample introduces
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
)

# Editable on the credentials page. `LXO_MCP_TOOL_POLICY` is deliberately not:
# it decides which policy file this interface is editing, and changing that
# from inside would swap the page's own subject out under it. The command line
# says which one to work on, and the overview shows which one won.
EDITABLE_KEYS: tuple[str, ...] = tuple(
    key for key in SETTING_KEYS if key not in ("LXO_MCP_API_KEY", "LXO_MCP_TOOL_POLICY")
)

API_KEY = "LXO_MCP_API_KEY"
POLICY_KEY = "LXO_MCP_TOOL_POLICY"


@dataclass
class Installation:
    """The files this interface acts on, and the settings they produce."""

    settings: Settings
    env_path: Path
    cwd: Path = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        # What `--tools-file` said, kept so that a later reload cannot lose
        # it. Resolving the settings again reads only files and the
        # environment, and the command line is in neither.
        self._named_policy = self.settings.tool_policy_path

    @property
    def policy(self) -> ToolPolicy:
        """The policy file in effect, re-read on every question."""
        return ToolPolicy(self.settings.policy_file())

    @property
    def profiles(self) -> ProfileStore:
        """The saved profiles that belong to that policy file."""
        return ProfileStore(profile_file(self.settings.policy_file()))

    def reload(self) -> None:
        """Resolve the settings again, after something was written.

        The policy file named on the command line survives this. Without
        that, saving a key would quietly move the interface to whichever
        policy file the search finds, and the page would go on claiming to
        edit the one it was started with.
        """
        fresh = load_settings(env_file=self.env_path, cwd=self.cwd)
        if self._named_policy is not None:
            fresh = dataclasses.replace(fresh, tool_policy_path=self._named_policy)
        self.settings = fresh

    # --- where a value comes from ------------------------------------------
    # In the order that decides: a real environment variable, then the command
    # line for the one setting it can name, then a .env, then the built-in
    # default. A .env that is not the one being written gets its own answer,
    # because typing over such a value here would appear to work and change
    # nothing.

    def file_env(self) -> dict[str, str]:
        """What the file this interface writes to holds right now."""
        return read_env_file(self.env_path)

    def searched_env(self) -> dict[str, str]:
        """Every ``.env`` the search finds, merged, highest precedence last.

        The environment is left out on purpose: this is what the *files* say,
        which is the half a person can edit here.
        """
        merged: dict[str, str] = {}
        for path in config_candidates(".env", self.cwd):
            merged.update(read_env_file(path))
        merged.update(read_env_file(self.env_path))
        return merged

    def source_of(self, key: str) -> str:
        """Which of the five places this value actually comes from."""
        if os.environ.get(key, "").strip():
            return ENV_SOURCE
        if key == POLICY_KEY and self.settings.tool_policy_path is not None:
            return CLI_SOURCE
        supplier = self.source_file(key)
        if supplier is None:
            return DEFAULT_SOURCE
        return FILE_SOURCE if supplier == self.env_path else OTHER_FILE_SOURCE

    def source_file(self, key: str) -> Path | None:
        """The ``.env`` that supplies this value, if a file does.

        Highest precedence first, so the answer is the file that wins rather
        than the first one that happens to mention the key.
        """
        if self.shadowed(key):
            return None
        for path in reversed([*config_candidates(".env", self.cwd), self.env_path]):
            if read_env_file(path).get(key, "").strip():
                return path
        return None

    def source_detail(self, key: str) -> str:
        """A tooltip for the badge: which file, or which variable."""
        if self.shadowed(key):
            return f"Umgebungsvariable {key}"
        if key == POLICY_KEY and self.settings.tool_policy_path is not None:
            return "Mit --tools-file auf der Kommandozeile benannt."
        supplier = self.source_file(key)
        return str(supplier) if supplier is not None else ""

    def shadowed(self, key: str) -> bool:
        """Whether writing this key here would have no effect.

        True when a real environment variable sets it, which outranks every
        file. Worth saying before somebody types a value into a form and
        wonders why the server ignores it.
        """
        return bool(os.environ.get(key, "").strip())

    def has_api_key(self) -> bool:
        return bool(self.settings.api_key)
