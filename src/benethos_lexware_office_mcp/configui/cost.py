"""What each tool costs in the model's context, measured rather than guessed.

Every enabled tool is sent to the model on **every** request, name, schemas
and description together. Section 8 of SPECS.md measures the whole list at
around two thousand characters per tool, and the six structured writing tools
carry half of it. That is the number this interface puts next to the checkbox:
switching a tool on is a permission decision and a budget decision at the same
time, and the second one is invisible everywhere else.

Measured the way the tool list is actually serialized — compact JSON, aliases
applied, empty fields dropped — so it is the same figure the CLAUDE.md
one-liner reports, not an approximation of it.
"""

from __future__ import annotations

import asyncio
import json

from mcp.server.mcpserver import MCPServer

from ..config import Settings

__all__ = ["CHARS_PER_TOKEN", "estimate_tokens", "tool_costs"]

# The list is JSON with long identifiers in it, which tokenizes worse than
# prose. Deliberately a range rather than a number: counting exactly would
# mean shipping a tokenizer to answer a question that only ever informs a
# judgement about whether a tool is worth its place.
CHARS_PER_TOKEN = 3.5

_measured: dict[str, int] | None = None


def tool_costs(settings: Settings) -> dict[str, int]:
    """Characters of context per tool, for every tool that exists.

    Measured once per process. Schemas and descriptions come from the code,
    not from the configuration, so the answer cannot change while the
    interface is running — and building a server is not free.
    """
    global _measured
    if _measured is None:
        _measured = asyncio.run(_measure(settings))
    return dict(_measured)


def estimate_tokens(characters: int) -> int:
    """Roughly what a character count costs in tokens."""
    return round(characters / CHARS_PER_TOKEN)


async def _measure(settings: Settings) -> dict[str, int]:
    # Imported here rather than at the top: `server` reaches back for this
    # package to offer the setup command, and a module-level import would
    # close the circle.
    from ..server import build_server

    server = build_server(settings)
    # Deliberately the unfiltered listing. `PolicyServer.list_tools` answers
    # with what this installation has switched on, and the cost of a tool has
    # to be visible before it is switched on, not after.
    tools = await MCPServer.list_tools(server)
    return {
        tool.name: len(
            json.dumps(
                tool.model_dump(exclude_none=True, by_alias=True),
                separators=(",", ":"),
                default=str,
            )
        )
        for tool in tools
    }
