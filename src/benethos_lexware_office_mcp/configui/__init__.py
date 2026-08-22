"""The local configuration interface: three pages in a browser.

Started with ``benethos-lexware-office-mcp setup`` and stopped with Ctrl+C. It
edits the same three files the server reads — the ``.env``, ``tools.json`` and
the profiles beside it — and holds no state of its own beyond the account name
from the last connection test.

Everything a person reads here is German. Lexware Office is sold for German
companies only, and its own help centre rules out an Austrian or Swiss company
as the account holder, so a language switch would be machinery for a case that
does not exist. Code, comments and docstrings are English as everywhere else.

The modules, in the order they depend on each other:

- ``render`` — the page shell, the stylesheet, the small pieces of markup
- ``state`` — which files apply and where each value came from
- ``cost`` — what a tool costs in the model's context, measured once
- ``probe`` — the one API call this interface makes, on request
- ``profiles`` — named sets of permissions
- ``transfer`` — the profile export, and reading one back
- ``pages`` — the three screens, pure functions from state to bytes
- ``app`` — the HTTP server, the routing, and the two CSRF guards
"""

from __future__ import annotations

from pathlib import Path

from ..config import Settings, resolve_config_file
from .app import DEFAULT_PORT, serve
from .state import Installation

__all__ = ["DEFAULT_PORT", "Installation", "start", "target_env_file"]


def target_env_file(named: Path | None = None, cwd: Path | None = None) -> Path:
    """The ``.env`` this interface writes to.

    A file named on the command line, or else the one the search would read —
    and when there is none anywhere, the per-user configuration directory,
    which is where an installed copy should create one. It does not have to
    exist yet: creating it is half of what this interface is for.
    """
    return named if named is not None else resolve_config_file(".env", cwd)


def start(
    settings: Settings,
    env_path: Path,
    *,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    cwd: Path | None = None,
) -> None:
    """Serve the interface until interrupted."""
    installation = Installation(
        settings=settings, env_path=env_path, cwd=cwd or Path.cwd()
    )
    serve(installation, port=port, open_browser=open_browser)
