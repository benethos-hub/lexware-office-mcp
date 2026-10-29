"""Tool registration.

One module per resource group. Each module exposes ``register(server,
settings, provider)`` and registers everything it has: what a client is
offered and what it may call is decided by the policy file, not here. See
:func:`._base.register_tool`. The one exception is ``server_status``, which
the server offers whatever the file says, see :mod:`.status`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from mcp.server.mcpserver import MCPServer

from ..api.client import ClientProvider
from ..settings import Settings
from . import (
    articles,
    contacts,
    deeplinks,
    diagnostics,
    files,
    master_data,
    sales_documents,
    status,
    vouchers,
)
from ._base import register_tool
from .files import DOWNLOAD_TOOLS
from .status import ALWAYS_OFFERED

__all__ = ["ALWAYS_OFFERED", "DOWNLOAD_TOOLS", "register_tool", "register_tools"]

Registrar = Callable[[MCPServer, Settings, ClientProvider], None]

# Order is the order tools are listed.
_MODULES: Sequence[Registrar] = (
    status.register,
    diagnostics.register,
    contacts.register,
    articles.register,
    vouchers.register,
    sales_documents.register,
    files.register,
    deeplinks.register,
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
