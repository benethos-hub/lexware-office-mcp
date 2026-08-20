"""Tool registration.

One module per resource group. Each module exposes ``register(server,
settings)`` and registers only the tools the active permission tier allows, so
a tool above the tier never reaches the client's tool list at all.

"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from mcp.server.mcpserver import MCPServer

from ..config import Settings
from . import diagnostics
from ._base import register_tool

__all__ = ["register_tool", "register_tools"]

Registrar = Callable[[MCPServer, Settings], None]

# Filled in as the tool modules appear. Order is the order tools are listed.
_MODULES: Sequence[Registrar] = (diagnostics.register,)


def register_tools(server: MCPServer, settings: Settings) -> None:
    """Register every tool the active permission tier allows."""
    for register in _MODULES:
        register(server, settings)
