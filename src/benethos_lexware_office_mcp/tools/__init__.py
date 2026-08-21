"""Tool registration.

One module per resource group. Each module exposes ``register(server,
settings, provider)`` and registers everything it has: what a client is
offered and what it may call is decided by the policy file, not here. See
:func:`._base.register_tool`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from mcp.server.mcpserver import MCPServer

from ..client import ClientProvider
from ..config import Settings
from . import contacts, diagnostics, files, master_data, sales_documents, vouchers
from ._base import register_tool

__all__ = ["register_tool", "register_tools"]

Registrar = Callable[[MCPServer, Settings, ClientProvider], None]

# Filled in as the tool modules appear. Order is the order tools are listed.
_MODULES: Sequence[Registrar] = (
    diagnostics.register,
    contacts.register,
    vouchers.register,
    sales_documents.register,
    files.register,
    master_data.register,
)


def register_tools(
    server: MCPServer, settings: Settings, provider: ClientProvider
) -> None:
    """Register every tool there is.

    Every module gets the same ``provider``, so every tool ends up sharing one
    client and therefore one rate limiter.
    """
    for register in _MODULES:
        register(server, settings, provider)
