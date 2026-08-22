"""``benethos-lexware-office-mcp setup``: what the command line hands over."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from benethos_lexware_office_mcp import configui, server
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.configui import pins as pins_module
from benethos_lexware_office_mcp.configui.pins import PINS_NAME, Pins, write_pins


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record what would be served instead of serving it."""
    calls: list[dict[str, Any]] = []

    def fake_start(settings: Settings, env_path: Path, **kwargs: Any) -> None:
        calls.append({"settings": settings, "env_path": env_path, **kwargs})

    monkeypatch.setattr(configui, "start", fake_start)
    return calls


def test_setup_serves_instead_of_starting_the_server(
    started: list[dict[str, Any]], tmp_path: Path
) -> None:
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_PAGE_SIZE=40\n", encoding="utf-8")

    server.main(["setup", "--env-file", str(env), "--no-browser", "--port", "9999"])

    assert len(started) == 1
    assert started[0]["env_path"] == env
    assert started[0]["port"] == 9999
    assert started[0]["open_browser"] is False
    assert started[0]["settings"].page_size == 40


def test_setup_does_not_insist_the_env_file_already_exists(
    started: list[dict[str, Any]], tmp_path: Path
) -> None:
    """Creating one is half of what the interface is for."""
    absent = tmp_path / "not-yet" / ".env"

    server.main(["setup", "--env-file", str(absent), "--no-browser"])

    assert started[0]["env_path"] == absent


def test_every_other_command_still_insists(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exit_code:
        server.main(["--tools", "show", "--env-file", str(tmp_path / "absent.env")])

    assert exit_code.value.code == 2


def test_the_named_policy_file_is_the_one_edited(
    started: list[dict[str, Any]], tmp_path: Path
) -> None:
    policy = tmp_path / "elsewhere.json"

    server.main(["setup", "--no-browser", "--tools-file", str(policy)])

    assert started[0]["settings"].policy_file() == policy


def test_without_a_named_file_the_search_decides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """And when nothing is found, the place to create one is the answer."""
    monkeypatch.setattr(
        configui, "resolve_config_file", lambda name, cwd=None: tmp_path / name
    )

    assert configui.target_env_file() == tmp_path / ".env"


def test_a_named_file_wins_over_the_search(tmp_path: Path) -> None:
    named = tmp_path / "named.env"

    assert configui.target_env_file(named) == named


@pytest.fixture
def pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / PINS_NAME
    monkeypatch.setattr(pins_module, "pins_file", lambda: target)
    return target


def test_setup_uses_the_files_it_was_told_to_remember(
    started: list[dict[str, Any]], pinned: Path, tmp_path: Path
) -> None:
    """The client's arguments are invisible from here, so they get written
    down once instead."""
    env = tmp_path / "remembered.env"
    env.write_text("LXO_MCP_PAGE_SIZE=44", encoding="utf-8")
    policy = tmp_path / "remembered.json"
    write_pins(Pins(env_file=env, tools_file=policy))

    server.main(["setup", "--no-browser"])

    assert started[0]["env_path"] == env
    assert started[0]["settings"].policy_file() == policy
    assert started[0]["settings"].page_size == 44


def test_the_command_line_still_wins_over_what_was_remembered(
    started: list[dict[str, Any]], pinned: Path, tmp_path: Path
) -> None:
    write_pins(
        Pins(env_file=tmp_path / "remembered.env", tools_file=tmp_path / "r.json")
    )
    named_env = tmp_path / "named.env"
    named_policy = tmp_path / "named.json"

    server.main(
        [
            "setup",
            "--no-browser",
            "--env-file",
            str(named_env),
            "--tools-file",
            str(named_policy),
        ]
    )

    assert started[0]["env_path"] == named_env
    assert started[0]["settings"].policy_file() == named_policy


def test_the_server_itself_ignores_the_remembered_files(
    pinned: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the interface moves. The policy the server enforces does not."""
    write_pins(
        Pins(env_file=tmp_path / "remembered.env", tools_file=tmp_path / "r.json")
    )
    searched = tmp_path / "searched.json"
    monkeypatch.setattr(
        "benethos_lexware_office_mcp.config.tool_policy_file", lambda: searched
    )
    seen: list[Path | None] = []
    monkeypatch.setattr(
        server, "build_server", lambda s: seen.append(s.policy_file()) or _Stub()
    )
    monkeypatch.setattr(server, "_report_what_is_enabled", lambda s: None)

    server.main([])

    assert seen == [searched]


class _Stub:
    def run(self) -> None:
        return None
