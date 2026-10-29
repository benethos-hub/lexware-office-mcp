"""``server_status``: which server is running, answered from memory.

The one tool outside the policy file, see SPECS.md section 9.2. It reads no
record and writes nothing, and with every other tool off it is what a model
can still ask. So it is listed and callable whatever the file says, it
never fails, and it writes no line of its own: a status question is not an
activity worth a line on stderr.

The answer is plain text, one ``key: value`` per line, in an order that
never changes. A field may be added after the others, never renamed or
removed, see SPECS.md section 8.
"""

from __future__ import annotations

import importlib.metadata
import sys
import time
from collections.abc import Callable

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from .. import __version__
from ..api.client import ClientProvider
from ..settings import Settings
from ._base import tidy

__all__ = ["ALWAYS_OFFERED", "NAME", "register", "render"]

NAME = "server_status"

# What the server lists and lets through before it asks the policy file.
ALWAYS_OFFERED = frozenset({NAME})

# A block is its fields in order, each a value or a block of its own.
Block = list[tuple[str, "str | Block"]]


def _mcp_version() -> str:
    """The version of the MCP library, as its package names it."""
    try:
        return importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def render(block: Block, depth: int = 0) -> list[str]:
    """``block`` as lines: ``key: value``, a nested block indented below its key."""
    lines: list[str] = []
    for key, value in block:
        indent = "  " * depth
        if isinstance(value, list):
            lines.append(f"{indent}{key}:")
            lines += render(value, depth + 1)
        else:
            lines.append(f"{indent}{key}: {value}")
    return lines


def register(
    server: MCPServer,
    settings: Settings,
    provider: ClientProvider,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Register ``server_status``. Building the server is where the uptime starts.

    Not through :func:`._base.register_tool`: that one puts the policy guard
    and the call log around a tool, and this one answers to neither.
    """
    started = clock()
    python = ".".join(str(part) for part in sys.version_info[:3])
    mcp = _mcp_version()

    def core() -> Block:
        return [
            ("name", server.name),
            ("version", __version__),
            ("transport", settings.transport),
            ("python", python),
            ("mcp", mcp),
            ("uptime_seconds", str(int(clock() - started))),
        ]

    async def server_status() -> CallToolResult:
        """Report which server is running: name, version, transport, Python and
        MCP library versions and uptime, without an API call.
        """
        text = "\n".join(render(core()))
        return CallToolResult(content=[TextContent(type="text", text=text)])

    tidy(server_status)
    server.tool(
        title="Server status",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
        ),
        structured_output=False,
    )(server_status)
