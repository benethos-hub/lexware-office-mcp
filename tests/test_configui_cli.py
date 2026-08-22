"""``benethos-lexware-office-mcp setup``: what the command line hands over."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from benethos_lexware_office_mcp import configui, server
from benethos_lexware_office_mcp.config import Settings


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
