"""The server as a real process, over the real transport.

Every other test calls the server in-process. This one spawns
``python -m benethos_lexware_office_mcp``, speaks MCP to it over stdio and
reads the answer back, which is what a client such as Claude Desktop actually
does.

It also proves golden rule 4 for free: stdout carries the JSON-RPC stream, so
a stray ``print`` anywhere on the import or startup path would corrupt the
handshake and this test would fail rather than the user's session.

No API key and no network: listing tools reaches nothing outside the process.
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def server_parameters(tmp_path: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "benethos_lexware_office_mcp"],
        # A directory of its own, so no `.env` beside the caller is read.
        cwd=str(tmp_path),
        env={
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            "PYTHONIOENCODING": "utf-8",
            "LXO_MCP_LOG_LEVEL": "ERROR",
            # A working directory of its own is not enough: the server also
            # reads the checkout's own config/.env, which on a developer
            # machine holds a real key. A real environment variable outranks
            # every file, so setting it empty keeps this test away from any
            # credential. Listing tools needs none.
            "LXO_MCP_API_KEY": "",
        },
    )


async def test_a_client_can_connect_and_list_the_tools(tmp_path: Path) -> None:
    async with stdio_client(server_parameters(tmp_path)) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()

    assert init.server_info.name == "benethos-lexware-office-mcp"
    assert "get_profile" in [tool.name for tool in tools.tools]


async def test_the_handshake_survives_the_whole_startup_path(tmp_path: Path) -> None:
    """If anything wrote to stdout, initialize would not have parsed."""
    async with stdio_client(server_parameters(tmp_path)) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()

    assert init.instructions is not None
    assert "Read-only" in init.instructions


async def test_no_write_tool_is_offered_by_default(tmp_path: Path) -> None:
    """The permission tier holds across a process boundary, not just in-process."""
    async with stdio_client(server_parameters(tmp_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

    names = [tool.name for tool in tools.tools]
    assert not any(name.startswith(("create_", "update_", "delete_")) for name in names)
