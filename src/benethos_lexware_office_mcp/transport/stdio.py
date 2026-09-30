"""The stdio transport: the client owns the process.

A client such as Claude Desktop starts this server as its own child and
speaks JSON-RPC over its stdin and stdout. Nothing else can reach it, so
none of the guards in :mod:`.http` apply - and stdout carries the stream,
so nothing but the SDK may write there. See SPECS.md section 6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from mcp.server.mcpserver import MCPServer

__all__ = ["run_stdio"]


def run_stdio(server: MCPServer) -> None:
    """Serve over stdin and stdout until the client closes them."""
    server.run("stdio")
