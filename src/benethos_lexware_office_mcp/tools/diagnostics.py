"""Profile and connection check."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from .. import formatting
from ..client import ClientProvider
from ..config import Settings
from ..policy import requires, should_register
from ._base import register_tool

__all__ = ["register"]


def register(server: MCPServer, settings: Settings, provider: ClientProvider) -> None:
    """Register the diagnostics tools allowed at the active permission tier."""

    @requires("read")
    async def get_profile() -> dict[str, Any]:
        """Show which Lexware Office account this server is connected to.

        Returns the organization, company name, tax setup and small-business
        status. Costs one API call.

        Use this first when the answer depends on *which* account is in play,
        and before any operation that changes data, so that the organization
        can be confirmed rather than assumed. It also doubles as the
        connection check: if it succeeds, the API key works.
        """
        return formatting.profile(await provider.get().profile())

    if should_register("read", settings.mode):
        register_tool(server, get_profile)
