"""The MCP hints a tool carries, and that they agree with its classification.

The protocol calls these hints and tells a client not to trust them from a
server it does not trust. Nothing here enforces anything, then — the policy
file decides what may be called. What these tests guard is that the hints say
the same thing the classification does, because two descriptions of one tool
are two chances to be wrong.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from mcp.types import Tool

from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.policy import known_tools
from benethos_lexware_office_mcp.server import build_server
from benethos_lexware_office_mcp.tools._base import _CLOSED_WORLD


@pytest.fixture
def listed(tmp_path: Path) -> dict[str, Tool]:
    """Every tool there is, listed, with the policy file allowing all of them."""
    target = tmp_path / "tools.json"
    target.write_text(json.dumps(dict.fromkeys(known_tools(), True)), encoding="utf-8")
    server = build_server(Settings(tool_policy_path=target))

    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def test_every_tool_carries_hints(listed: dict[str, Tool]) -> None:
    assert set(listed) == set(known_tools())
    missing = [name for name, tool in listed.items() if tool.annotations is None]
    assert not missing, f"no annotations on {missing}"


def test_reading_and_writing_are_never_confused(listed: dict[str, Tool]) -> None:
    """The one hint a client is most likely to act on without asking."""
    for name, meta in known_tools().items():
        hints = listed[name].annotations
        assert hints is not None
        assert hints.read_only_hint is (meta.access == "read"), name


def test_a_create_only_adds_and_is_not_idempotent(listed: dict[str, Tool]) -> None:
    """No idempotency key exists, so a second call makes a second record.

    Measured against the live API on 2026-08-21, see SPECS.md section 16.
    """
    creates = [n for n, m in known_tools().items() if m.effect == "create"]
    assert creates, "the fixture would prove nothing without one"
    for name in creates:
        hints = listed[name].annotations
        assert hints is not None
        assert hints.destructive_hint is False, name
        assert hints.idempotent_hint is False, name


def test_an_update_or_a_delete_says_it_destroys(listed: dict[str, Tool]) -> None:
    """An update replaces the record: this API has no patch."""
    changes = [n for n, m in known_tools().items() if m.effect in ("update", "delete")]
    assert changes
    for name in changes:
        hints = listed[name].annotations
        assert hints is not None
        assert hints.destructive_hint is True, name
        assert hints.idempotent_hint is True, name


def test_only_the_two_tools_that_reach_nothing_say_so(listed: dict[str, Tool]) -> None:
    """`open_world_hint` is stated where it differs from what MCP assumes."""
    closed = {
        n
        for n, t in listed.items()
        if t.annotations is not None and t.annotations.open_world_hint is False
    }

    assert closed == set(_CLOSED_WORLD)
    for name in _CLOSED_WORLD:
        assert known_tools()[name].access == "read", name
