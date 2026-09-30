"""Profile and connection check."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from ..api.client import ClientProvider
from ..policy import classify
from ..records import formatting
from ..settings import Settings
from ._base import register_tool

__all__ = ["register"]


def register(server: MCPServer, settings: Settings, provider: ClientProvider) -> None:
    """Register the diagnostics tools. The policy file decides the rest."""

    @classify("read", "diagnostics")
    async def get_profile() -> dict[str, Any]:
        """Show which Lexware Office account this server is connected to.

        One API call. Returns the organization, company name, tax setup and
        small-business status.

        Call it before anything that changes data, so the organization is
        confirmed rather than assumed. It doubles as the connection check: if
        it succeeds, the API key works.
        """
        return formatting.profile(await provider.get().profile())

    register_tool(server, get_profile)
