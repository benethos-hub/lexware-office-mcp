"""The per-tool policy file: what it turns off, and what it cannot turn on."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.errors import PermissionDeniedError
from benethos_lexware_office_mcp.policy import (
    ToolPolicy,
    known_tools,
    preset,
    set_active_policy,
)
from benethos_lexware_office_mcp.server import build_server, main

pytestmark = pytest.mark.anyio

API_KEY = "test-key"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def write(path: Path, flags: dict[str, bool]) -> Path:
    path.write_text(json.dumps(flags), encoding="utf-8")
    return path


# -- the default ----------------------------------------------------------


# Named rather than read back from the registry, which the decorator also
# fills with the sample tools other test modules define.
SHIPPED = {
    "get_profile",
    "search_contacts",
    "get_contact",
    "create_contact",
    "update_contact",
    "search_vouchers",
    "get_voucher",
    "get_payments",
    "create_voucher",
    "update_voucher",
    "download_file",
    "download_document",
    "get_deeplink",
    "read_download",
    "upload_file",
}


async def test_without_a_file_every_tool_is_listed(tmp_path: Path) -> None:
    """An installation nobody configured behaves as it did before the file."""
    settings = Settings(
        api_key=API_KEY, mode="full", tool_policy_path=tmp_path / "absent.json"
    )

    names = {t.name for t in await build_server(settings).list_tools()}

    assert names == SHIPPED


async def test_a_tool_the_file_does_not_mention_stays_on(tmp_path: Path) -> None:
    """The file takes something away. Silence is not a refusal."""
    policy = write(tmp_path / "tools.json", {"search_contacts": False})
    settings = Settings(api_key=API_KEY, mode="full", tool_policy_path=policy)

    names = {t.name for t in await build_server(settings).list_tools()}

    assert "search_contacts" not in names
    assert "get_contact" in names


# -- both gates -----------------------------------------------------------


async def test_a_disabled_tool_is_not_listed(tmp_path: Path) -> None:
    policy = write(tmp_path / "tools.json", {"download_file": False})
    settings = Settings(api_key=API_KEY, tool_policy_path=policy)

    names = {t.name for t in await build_server(settings).list_tools()}

    assert "download_file" not in names
    assert "download_document" in names


async def test_a_disabled_tool_is_refused_even_when_called_anyway() -> None:
    """A client holding a list from before the change must not get through."""
    set_active_policy(ToolPolicy())
    from benethos_lexware_office_mcp.policy import requires

    @requires("read")
    async def sample_tool() -> str:
        return "ran"

    assert await sample_tool() == "ran"

    class Off(ToolPolicy):
        def enabled(self, name: str) -> bool:
            return False

    set_active_policy(Off())
    try:
        with pytest.raises(PermissionDeniedError) as excinfo:
            await sample_tool()
    finally:
        set_active_policy(ToolPolicy())

    assert "switched off" in str(excinfo.value)


async def test_the_file_cannot_grant_what_the_tier_withholds(tmp_path: Path) -> None:
    """Two gates, and a tool has to pass both.

    Enabling a write tool in the file while the server runs read-only would
    otherwise turn a configuration file into a way around `LXO_MCP_MODE`.
    """
    policy = write(tmp_path / "tools.json", dict.fromkeys(SHIPPED, True))
    settings = Settings(api_key=API_KEY, mode="read", tool_policy_path=policy)

    names = {t.name for t in await build_server(settings).list_tools()}

    assert "create_contact" not in names


# -- a file written by hand -----------------------------------------------


async def test_a_broken_file_does_not_stop_the_server(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """It is edited by hand, so it will be broken eventually."""
    policy = tmp_path / "tools.json"
    policy.write_text("{not json at all", encoding="utf-8")
    settings = Settings(api_key=API_KEY, tool_policy_path=policy)

    with caplog.at_level(logging.WARNING):
        names = {t.name for t in await build_server(settings).list_tools()}

    assert "get_profile" in names
    assert "unreadable tool policy" in caplog.text.lower()


async def test_a_file_holding_something_other_than_an_object_is_ignored(
    tmp_path: Path,
) -> None:
    policy = tmp_path / "tools.json"
    policy.write_text('["get_profile"]', encoding="utf-8")

    assert ToolPolicy(policy).enabled("get_profile") is True


async def test_the_file_is_re_read_rather_than_remembered(tmp_path: Path) -> None:
    """Edited while the server runs, it takes effect on the next question."""
    policy = write(tmp_path / "tools.json", {"get_profile": True})
    store = ToolPolicy(policy)

    assert store.enabled("get_profile") is True
    write(policy, {"get_profile": False})

    assert store.enabled("get_profile") is False


# -- presets write files, they are not consulted --------------------------


def test_the_read_only_preset_keeps_exactly_the_reading_tools() -> None:
    flags = preset("read-only")

    assert set(flags) == set(known_tools())
    for name, tier in known_tools().items():
        assert flags[name] is (tier == "read"), name


def test_the_all_preset_turns_everything_on() -> None:
    assert set(preset("all").values()) == {True}


def test_an_unknown_preset_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown preset"):
        preset("everything-plus")  # type: ignore[arg-type]


def test_saving_writes_every_tool_not_only_the_exceptions(tmp_path: Path) -> None:
    """The file is an inventory. A reader should not have to know the default."""
    policy = ToolPolicy(tmp_path / "nested" / "tools.json")

    policy.save({"get_profile": False})

    stored = json.loads((tmp_path / "nested" / "tools.json").read_text())
    assert set(stored) == set(known_tools())
    assert stored["get_profile"] is False
    assert stored["search_contacts"] is False, "an unnamed tool is off, not defaulted"


def test_a_policy_without_a_file_refuses_to_save() -> None:
    with pytest.raises(ValueError, match="no file"):
        ToolPolicy().save({})


# -- the command line -----------------------------------------------------


def test_the_command_line_writes_the_preset_and_does_not_serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """It shares an entry point with the server, so stdout stays untouched."""
    policy = tmp_path / "tools.json"
    monkeypatch.setenv("LXO_MCP_TOOL_POLICY", str(policy))

    main(["--tools", "read-only"])

    stored = json.loads(policy.read_text())
    assert stored["search_vouchers"] is True
    assert stored["create_voucher"] is False

    captured = capsys.readouterr()
    assert captured.out == "", "stdout carries the JSON-RPC stream"
    assert "read-only" in captured.err
