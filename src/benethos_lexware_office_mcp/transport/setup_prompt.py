"""The configuration interface, opened from a prompt the person picks.

A client that starts this server over stdio may run it where nothing else
can: Claude Desktop's extensions live in a sandbox whose Python cannot be
started from outside it. A prompt is the one thing such a client lets a
person trigger from its own window, so the server offers one that starts
``setup`` as a process of its own, inside the same sandbox, and the browser
opens on the start code. See SPECS.md section 7.1.

A prompt is user-controlled, never the model's to call, so this does not
weaken the rule that the policy file alone decides what exists: the prompt
reaches no data and changes nothing, and what the page saves is decided by
the person in front of it. Over HTTP it is not offered at all, since a
remote client would open a page on a machine it does not sit at.
"""

from __future__ import annotations

import socket
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from .. import logbook
from ..server import SETUP_PROMPT_TITLE

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from mcp.server.mcpserver import MCPServer

__all__ = ["SETUP_PROMPT", "SETUP_PROMPT_TEXT", "offer_setup", "setup_command"]

SETUP_PROMPT = "open_setup"

# How long the interface the prompt opened waits for a request before it
# ends itself. Nobody started it from a terminal, so nothing else ends it,
# and while it runs it holds the extension's Python, which on Windows keeps
# Claude Desktop from removing or updating the extension.
IDLE_MINUTES = 30

# The one answer, whatever happened. Claude Desktop holds a prompt's answer
# against the text its extension declared and rejects anything else as a
# possible injection, so this cannot carry what happened - stderr does.
SETUP_PROMPT_TEXT = (
    "The configuration interface of the Lexware Office MCP server is open in "
    "the browser, where the person sets the API key and which tools exist. "
    "Nothing needs to be done in this conversation."
)


def setup_command(env_file: Path | None, tools_file: Path | None) -> list[str]:
    """``setup`` on the files this server was started with, and only those.

    A file is named only when the server was given one. Naming the default
    would make the page tell a person who never configured a client to put
    `--env-file` into one.
    """
    command = [
        sys.executable,
        "-m",
        "benethos_lexware_office_mcp",
        "setup",
        "--exit-when-idle",
        str(IDLE_MINUTES),
    ]
    if env_file is not None:
        command += ["--env-file", str(env_file)]
    if tools_file is not None:
        command += ["--tools-file", str(tools_file)]
    return command


def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _start(command: Sequence[str]) -> None:
    """A process that outlives this one, with no hold on its streams.

    stdout is the JSON-RPC stream, so the child gets none of it, and it is
    detached so that a client restarting the server leaves the page open.
    """
    # sys.platform rather than os.name, which a type checker does not read:
    # the two flags exist only on Windows, and on Linux it would not know them.
    detached = 0
    if sys.platform == "win32":
        detached = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=detached,
        start_new_session=sys.platform != "win32",
    )


def offer_setup(
    server: MCPServer,
    *,
    port: int,
    env_file: Path | None,
    tools_file: Path | None,
    listening: Callable[[int], bool] = _listening,
    start: Callable[[Sequence[str]], None] = _start,
) -> None:
    """Register the prompt. ``listening`` and ``start`` are for tests."""

    @server.prompt(
        name=SETUP_PROMPT,
        title=SETUP_PROMPT_TITLE,
        description="Opens the configuration interface in the browser.",
    )
    def open_setup() -> str:
        if listening(port):
            logbook.lifecycle.setup_already_open(port)
            return SETUP_PROMPT_TEXT
        try:
            start(setup_command(env_file, tools_file))
        except OSError as error:
            logbook.lifecycle.setup_not_started(error)
        else:
            logbook.lifecycle.setup_started(port)
        return SETUP_PROMPT_TEXT
