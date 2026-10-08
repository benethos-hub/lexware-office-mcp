"""The local configuration interface: four pages in a browser.

Started with ``benethos-lexware-office-mcp setup`` and stopped with Ctrl+C. It
edits the same three files the server reads — the ``.env``, ``tools.json`` and
the profiles beside it — and holds no state of its own beyond the account name
from the last connection test.

Everything a person reads here is German. Lexware Office is sold for German
companies only, and its own help centre rules out an Austrian or Swiss company
as the account holder, so a language switch would be machinery for a case that
does not exist. Code, comments and docstrings are English as everywhere else.

The modules, in the order they depend on each other:

- ``cost`` — what a tool costs in the model's context, measured once
- ``templates`` — the one module importing Jinja2, the templates and the
  static files beside it
- ``stamp`` — when a profile was saved, to a resolution that is not invented
- ``profiles`` — named sets of permissions
- ``state`` — which files apply and where each value came from
- ``probe`` — the one API call this interface makes, on request
- ``transfer`` — a policy file written out, and read back in
- ``pages`` — the four screens, each a template and its context
- ``actions`` — what each form does, as plain functions without HTTP
- ``app`` — the HTTP server, the routing, and the two CSRF guards
"""

from __future__ import annotations

from pathlib import Path

from ..settings import DEFAULT_HTTP_HOST, DEFAULT_HTTP_PORT, Settings
from ..settings.locations import resolve_config_file
from .state import Installation

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "Installation",
    "start",
    "target_env_file",
]

# Loopback, as the transport binds by default. The port is one above the
# transport's, as the Compose files publish the two, so a server already
# listening on its port does not end `setup` with "in use".
DEFAULT_HOST = DEFAULT_HTTP_HOST
DEFAULT_PORT = DEFAULT_HTTP_PORT + 1


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
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    cwd: Path | None = None,
    tools_file_named: bool = False,
    public_port: int | None = None,
) -> None:
    """Serve the interface until interrupted.

    The pages are imported here rather than at the top: the console script
    imports this package for every start, the server's included, and the
    server has no reason to load a template engine.
    """
    from .app import serve

    installation = Installation(
        settings=settings,
        env_path=env_path,
        cwd=cwd or Path.cwd(),
        tools_file_named=tools_file_named,
    )
    serve(
        installation,
        host=host,
        port=port,
        open_browser=open_browser,
        public_port=public_port,
    )
