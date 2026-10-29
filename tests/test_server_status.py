"""``server_status``: the one tool the policy file does not decide.

Its answer is read by a model and by whoever asks in a chat, so the order and
the spelling of every line are part of what is tested, not only the values.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import httpx
import pytest
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

from benethos_lexware_office_mcp import __version__
from benethos_lexware_office_mcp.policy import ToolPolicy, known_tools, preset
from benethos_lexware_office_mcp.server import build_server
from benethos_lexware_office_mcp.settings import Settings
from benethos_lexware_office_mcp.tools import status
from helpers import API_KEY, fast_provider, server_obeying

CORE = ["name", "version", "transport", "python", "mcp", "uptime_seconds"]


def text_of(result: CallToolResult) -> str:
    assert result.is_error is not True
    assert result.structured_content is None
    [block] = result.content
    assert isinstance(block, TextContent)
    return block.text


def fields(text: str) -> list[tuple[str, str]]:
    """The answer's lines as pairs, a block's key with an empty value."""
    pairs = []
    for line in text.splitlines():
        key, _, value = line.partition(":")
        pairs.append((key, value.strip()))
    return pairs


def refusing(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"no request was expected, got {request.url}")


# -- the core -------------------------------------------------------------


async def test_the_core_names_its_fields_in_order_without_a_request() -> None:
    provider = fast_provider(refusing)
    server = build_server(Settings(api_key=API_KEY), provider)

    answer = dict(fields(text_of(await server.call_tool("server_status", {}))))

    assert list(answer) == CORE
    assert answer["name"] == "benethos-lexware-office-mcp"
    assert answer["version"] == __version__
    assert answer["transport"] == "stdio"
    assert answer["python"] == ".".join(str(n) for n in sys.version_info[:3])
    assert answer["mcp"].count(".") >= 1
    assert answer["uptime_seconds"].isdigit()


async def test_the_transport_is_the_one_this_process_runs() -> None:
    server = build_server(Settings(transport="streamable-http"))

    answer = dict(fields(text_of(await server.call_tool("server_status", {}))))

    assert answer["transport"] == "streamable-http"


async def test_the_uptime_counts_from_when_the_server_was_built() -> None:
    now = [100.0]
    server = MCPServer(name="benethos-lexware-office-mcp")
    status.register(
        server,
        Settings(),
        fast_provider(refusing),
        clock=lambda: now[0],
    )
    now[0] = 518.9

    answer = dict(fields(text_of(await server.call_tool("server_status", {}))))

    assert answer["uptime_seconds"] == "418"


async def test_it_writes_no_line_at_info(lines: pytest.LogCaptureFixture) -> None:
    """A status question is not an activity, so the call log stays quiet."""
    server = build_server(Settings())

    await server.call_tool("server_status", {})

    assert [r for r in lines.records if r.levelno >= logging.INFO] == []


# -- outside the policy ---------------------------------------------------


async def test_it_is_offered_and_answers_without_a_policy_file(tmp_path: Path) -> None:
    server = build_server(Settings(tool_policy_path=tmp_path / "absent.json"))

    assert [t.name for t in await server.list_tools()] == ["server_status"]
    assert text_of(await server.call_tool("server_status", {}))


async def test_a_file_that_switches_it_off_is_not_obeyed(tmp_path: Path) -> None:
    server = server_obeying(tmp_path, {"server_status": False})

    assert [t.name for t in await server.list_tools()] == ["server_status"]
    assert text_of(await server.call_tool("server_status", {}))


async def test_a_policy_that_fails_to_answer_is_not_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = server_obeying(tmp_path, {})

    def broken(self: ToolPolicy, name: str) -> bool:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(ToolPolicy, "enabled", broken)

    assert text_of(await server.call_tool("server_status", {}))


def test_it_is_no_tool_a_policy_or_a_preset_can_name() -> None:
    """Not in the registry, so neither the interface nor `--tools` shows it."""
    assert status.NAME not in known_tools()
    assert status.NAME not in preset("irreversible")


async def test_it_says_it_reads_and_changes_nothing() -> None:
    server = build_server(Settings())
    tool = next(t for t in await server.list_tools() if t.name == "server_status")

    assert tool.title == "Server status"
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.output_schema is None


# -- the form -------------------------------------------------------------


def test_a_block_is_indented_two_spaces_below_its_key() -> None:
    block: status.Block = [("a", "1"), ("b", [("c", "2"), ("d", [("e", "3")])])]

    assert status.render(block) == ["a: 1", "b:", "  c: 2", "  d:", "    e: 3"]
