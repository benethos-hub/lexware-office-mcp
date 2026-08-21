"""The server builds, identifies itself, and offers what the file allows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benethos_lexware_office_mcp import __version__, policy
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.server import build_server, main


def test_server_identifies_itself() -> None:
    server = build_server(Settings())
    assert server.name == "benethos-lexware-office-mcp"
    assert server.version == __version__


def test_building_a_server_activates_its_policy(tmp_path: Path) -> None:
    target = tmp_path / "tools.json"

    build_server(Settings(tool_policy_path=target))

    assert policy.active_policy().path == target


async def test_a_server_without_a_policy_file_offers_nothing(
    tmp_path: Path,
) -> None:
    """The state to be in when nobody has said what this server may touch.

    An empty tool list is a strange thing to ship, and it is the point: the
    file is the only gate now, so its absence has to mean no, not yes.
    """
    server = build_server(Settings(tool_policy_path=tmp_path / "absent.json"))

    assert await server.list_tools() == []


async def test_a_server_offers_exactly_what_the_file_names(tmp_path: Path) -> None:
    target = tmp_path / "tools.json"
    target.write_text(
        json.dumps({"get_profile": True, "search_contacts": False}), encoding="utf-8"
    )

    server = build_server(Settings(tool_policy_path=target))

    assert [t.name for t in await server.list_tools()] == ["get_profile"]


def test_starting_the_server_reports_what_is_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A client shows an empty tool list without explaining why. stderr does."""
    monkeypatch.setattr(
        "benethos_lexware_office_mcp.server.load_settings",
        lambda **_: Settings(tool_policy_path=tmp_path / "absent.json"),
    )
    started: list[bool] = []
    monkeypatch.setattr(
        "benethos_lexware_office_mcp.server.build_server",
        lambda settings: _FakeServer(started),
    )

    with caplog.at_level("WARNING"):
        main(["--log-level", "WARNING"])

    assert started == [True]
    assert "no tools are offered" in caplog.text
    assert "--tools read-only" in caplog.text


def test_starting_with_write_tools_on_says_which_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Naming them is the point: this server can change real records."""
    target = tmp_path / "tools.json"
    target.write_text(
        json.dumps({"get_profile": True, "upload_file": True}), encoding="utf-8"
    )
    monkeypatch.setattr(
        "benethos_lexware_office_mcp.server.load_settings",
        lambda **_: Settings(tool_policy_path=target),
    )
    monkeypatch.setattr(
        "benethos_lexware_office_mcp.server.build_server",
        lambda settings: _FakeServer([]),
    )

    with caplog.at_level("WARNING"):
        main(["--log-level", "WARNING"])

    assert "upload_file" in caplog.text
    assert "change real accounting records" in caplog.text


class _FakeServer:
    """Stands in for MCPServer so the test never opens stdio."""

    def __init__(self, started: list[bool]) -> None:
        self._started = started

    def run(self) -> None:
        self._started.append(True)


def test_a_named_env_file_that_is_not_there_stops_the_server(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Falling back to the search would be the worst of both.

    The server would start, read some other file, and behave in a way the
    command line appears to rule out. A typo has to be a refusal.
    """
    with pytest.raises(SystemExit) as excinfo:
        main(["--env-file", str(tmp_path / "typo.env")])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "", "stdout carries the JSON-RPC stream"
    assert "typo.env" in captured.err


def test_a_named_env_file_configures_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: one client entry, its own account and its own file."""
    env_file = tmp_path / "test.env"
    env_file.write_text("LXO_MCP_PAGE_SIZE=13\n", encoding="utf-8")
    seen: list[Settings] = []
    monkeypatch.setattr(
        "benethos_lexware_office_mcp.server.build_server",
        lambda settings: seen.append(settings) or _FakeServer([]),
    )

    main(["--env-file", str(env_file), "--log-level", "ERROR"])

    assert seen[0].page_size == 13
