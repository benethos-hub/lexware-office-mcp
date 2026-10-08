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

from helpers import write_policy


def server_parameters(
    tmp_path: Path, policy: Path | None = None
) -> StdioServerParameters:
    # A working directory of its own is not enough: the search also finds
    # the checkout's own config/.env, which on a developer machine holds a
    # real key. A file named on the command line replaces the search, so an
    # empty one keeps this test away from any credential. Listing tools
    # needs none.
    empty = tmp_path / "empty.env"
    empty.write_text("", encoding="utf-8")
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "benethos_lexware_office_mcp", "--env-file", str(empty)],
        cwd=str(tmp_path),
        env={
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            "PYTHONIOENCODING": "utf-8",
            "LXO_MCP_LOG_LEVEL": "ERROR",
            # Same reasoning for the policy. The checkout has a tools.json of
            # its own, holding whatever the developer enabled, and a
            # subprocess resolves it like any other installation would. Naming
            # a file that does not exist is what keeps this test about the
            # code rather than about one machine.
            "LXO_MCP_TOOL_POLICY": str(policy or tmp_path / "absent-tools.json"),
        },
    )


def enabling(tmp_path: Path, *names: str) -> Path:
    """A policy file switching exactly ``names`` on."""
    return write_policy(tmp_path / "tools.json", dict.fromkeys(names, True))


async def test_a_client_can_connect_and_list_the_tools(tmp_path: Path) -> None:
    policy = enabling(tmp_path, "get_profile")

    async with stdio_client(server_parameters(tmp_path, policy)) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()

    assert init.server_info.name == "benethos-lexware-office-mcp"
    assert [tool.name for tool in tools.tools] == ["get_profile"]


async def test_the_handshake_survives_the_whole_startup_path(tmp_path: Path) -> None:
    """If anything wrote to stdout, initialize would not have parsed."""
    async with stdio_client(server_parameters(tmp_path)) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()

    assert init.instructions is not None
    assert "account owner" in init.instructions


async def test_nothing_is_offered_without_a_policy_file(tmp_path: Path) -> None:
    """The gate holds across a process boundary, not just in-process.

    A subprocess is where a mistake would actually show: this is the shape a
    client launches, with no test fixture deciding anything for it.
    """
    async with stdio_client(server_parameters(tmp_path)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

    assert [tool.name for tool in tools.tools] == []
