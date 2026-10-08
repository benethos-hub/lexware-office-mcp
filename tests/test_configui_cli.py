"""``benethos-lexware-office-mcp setup``: what the command line hands over."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from benethos_lexware_office_mcp import cli, configui
from benethos_lexware_office_mcp.settings import DEFAULT_HTTP_PORT, Settings


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

    cli.main(["setup", "--env-file", str(env), "--no-browser", "--port", "9999"])

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

    cli.main(["setup", "--env-file", str(absent), "--no-browser"])

    assert started[0]["env_path"] == absent


def test_relative_files_are_made_absolute_at_start(
    started: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page compares them with the absolute paths of the search, and
    hands them to a client that starts in a directory of its own."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rel.env").write_text("", encoding="utf-8")

    cli.main(
        ["setup", "--env-file", "rel.env", "--tools-file", "t.json", "--no-browser"]
    )

    assert started[0]["env_path"] == tmp_path / "rel.env"
    assert started[0]["env_path"].is_absolute()
    assert started[0]["settings"].policy_file() == tmp_path / "t.json"
    assert started[0]["settings"].policy_file().is_absolute()


def test_every_other_command_still_insists(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exit_code:
        cli.main(["--tools", "show", "--env-file", str(tmp_path / "absent.env")])

    assert exit_code.value.code == 2


def test_the_named_policy_file_is_the_one_edited(
    started: list[dict[str, Any]], tmp_path: Path
) -> None:
    policy = tmp_path / "elsewhere.json"

    cli.main(["setup", "--no-browser", "--tools-file", str(policy)])

    assert started[0]["settings"].policy_file() == policy
    assert started[0]["tools_file_named"] is True


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


def test_setup_and_the_transport_do_not_share_a_default_port(
    started: list[dict[str, Any]], tmp_path: Path
) -> None:
    """Both on 8770, setup beside a running server ended with "in use"."""
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")

    cli.main(["setup", "--env-file", str(env), "--no-browser"])

    assert started[0]["port"] == configui.DEFAULT_PORT
    assert configui.DEFAULT_PORT != DEFAULT_HTTP_PORT
