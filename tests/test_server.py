"""The server builds, identifies itself, and honours the permission tier."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from benethos_lexware_office_mcp import __version__, policy
from benethos_lexware_office_mcp.config import Settings, load_settings
from benethos_lexware_office_mcp.server import build_server, main, replace_mode


@pytest.fixture(autouse=True)
def _restore_mode() -> Iterator[None]:
    previous = policy.active_mode()
    yield
    policy.set_active_mode(previous)


def test_server_identifies_itself() -> None:
    server = build_server(Settings())
    assert server.name == "benethos-lexware-office-mcp"
    assert server.version == __version__


def test_building_a_server_sets_the_active_tier() -> None:
    build_server(Settings(mode="write"))
    assert policy.active_mode() == "write"


async def test_a_default_server_lists_no_write_tools() -> None:
    """Whatever is registered, nothing above 'read' may be listed by default."""
    server = build_server(Settings())
    for tool in await server.list_tools():
        assert policy.required_tier(tool.name) in (None, "read")


def test_command_line_mode_beats_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benethos_lexware_office_mcp.server.load_settings",
        lambda: load_settings({"LXO_MCP_MODE": "read"}),
    )
    started: list[str] = []
    monkeypatch.setattr(
        "benethos_lexware_office_mcp.server.build_server",
        lambda settings: _FakeServer(started, settings.mode),
    )
    main(["--mode", "write", "--log-level", "ERROR"])
    assert started == ["write"]


def test_replace_mode_leaves_the_original_untouched() -> None:
    original = Settings(mode="read")
    changed = replace_mode(original, "full")
    assert original.mode == "read"
    assert changed.mode == "full"


class _FakeServer:
    """Stands in for MCPServer so the test never opens stdio."""

    def __init__(self, started: list[str], mode: str) -> None:
        self._started = started
        self._mode = mode

    def run(self) -> None:
        self._started.append(self._mode)
