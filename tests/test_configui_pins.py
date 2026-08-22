"""The two paths the interface remembers, and who is allowed to read them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.configui import pins as pins_module
from benethos_lexware_office_mcp.configui.pins import (
    PINS_NAME,
    Pins,
    read_pins,
    write_pins,
)


@pytest.fixture
def pinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A pointer file of this test's own, never the developer's."""
    target = tmp_path / PINS_NAME
    monkeypatch.setattr(pins_module, "pins_file", lambda: target)
    return target


def test_nothing_remembered_is_the_starting_state(pinned: Path) -> None:
    assert read_pins() == Pins()
    assert not read_pins()


def test_both_paths_survive_the_round_trip(pinned: Path, tmp_path: Path) -> None:
    write_pins(Pins(env_file=tmp_path / "a.env", tools_file=tmp_path / "b.json"))

    back = read_pins()
    assert back.env_file == tmp_path / "a.env"
    assert back.tools_file == tmp_path / "b.json"
    assert back


def test_only_what_is_set_is_written(pinned: Path, tmp_path: Path) -> None:
    write_pins(Pins(env_file=tmp_path / "a.env"))

    assert json.loads(pinned.read_text(encoding="utf-8")) == {
        "envFile": str(tmp_path / "a.env")
    }
    assert read_pins().tools_file is None


def test_the_file_and_its_directory_are_created(tmp_path: Path) -> None:
    target = tmp_path / "deeper" / PINS_NAME

    write_pins(Pins(env_file=tmp_path / "a.env"), target)

    assert target.is_file()


def test_an_unreadable_file_is_a_warning_and_not_a_stop(
    pinned: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Searching as before is a working state. Refusing to start is not."""
    pinned.write_text("{kaputt", encoding="utf-8")

    assert read_pins() == Pins()
    assert "Unreadable setup pointers" in caplog.text


@pytest.mark.parametrize("body", ["[]", '"text"', '{"envFile": 5}', '{"envFile": " "}'])
def test_anything_that_is_not_a_path_is_ignored(pinned: Path, body: str) -> None:
    pinned.write_text(body, encoding="utf-8")

    assert read_pins().env_file is None


# -- the rule this file lives under -----------------------------------------


def test_the_server_never_reads_the_pointers(
    pinned: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pointer file with a say in the policy would be a second gate.

    Section 9.2 has one gate. This file only ever moves the interface.
    """
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text('{"get_profile": true}', encoding="utf-8")
    write_pins(Pins(env_file=tmp_path / "a.env", tools_file=elsewhere))
    monkeypatch.setattr(
        "benethos_lexware_office_mcp.config.tool_policy_file",
        lambda: tmp_path / "searched.json",
    )

    settings = Settings()

    assert settings.policy_file() == tmp_path / "searched.json"
