"""The policy file: the only thing that decides what this server offers."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.policy import ToolPolicy, known_tools, preset
from benethos_lexware_office_mcp.server import build_server, main

pytestmark = pytest.mark.anyio

API_KEY = "test-key"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def write(path: Path, flags: dict[str, bool]) -> Path:
    path.write_text(json.dumps(flags), encoding="utf-8")
    return path


# -- silence is a refusal -------------------------------------------------


async def test_without_a_file_nothing_is_offered(tmp_path: Path) -> None:
    """The file is the only gate, so its absence has to mean no."""
    settings = Settings(api_key=API_KEY, tool_policy_path=tmp_path / "absent.json")

    assert await build_server(settings).list_tools() == []


async def test_a_tool_the_file_does_not_mention_is_off(tmp_path: Path) -> None:
    """Anything the file fails to say is a no, including by omission.

    A file listing what to *disable* would quietly enable every tool added
    later. This one lists what to allow, so a tool nobody has decided about
    stays out.
    """
    policy = write(tmp_path / "tools.json", {"get_contact": True})
    settings = Settings(api_key=API_KEY, tool_policy_path=policy)

    names = {t.name for t in await build_server(settings).list_tools()}

    assert names == {"get_contact"}


async def test_a_disabled_tool_is_not_listed(tmp_path: Path) -> None:
    policy = write(
        tmp_path / "tools.json", {"download_file": False, "download_document": True}
    )
    settings = Settings(api_key=API_KEY, tool_policy_path=policy)

    names = {t.name for t in await build_server(settings).list_tools()}

    assert "download_file" not in names
    assert "download_document" in names


async def test_a_write_tool_is_offered_when_the_file_says_so(tmp_path: Path) -> None:
    """There is no second gate above this one any more.

    The tier used to refuse a write tool whatever the file said. That is gone
    on purpose: one place decides, and this is it.
    """
    policy = write(tmp_path / "tools.json", {"upload_file": True})
    settings = Settings(api_key=API_KEY, tool_policy_path=policy)

    names = {t.name for t in await build_server(settings).list_tools()}

    assert names == {"upload_file"}


# -- a file written by hand and by other programs -------------------------


async def test_a_broken_file_enables_nothing_and_says_so(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """It is edited by hand, so it will be broken eventually.

    A parse error must not start a server that offers everything, and must not
    stop it starting either - the warning on stderr is what makes the empty
    tool list explicable.
    """
    policy = tmp_path / "tools.json"
    policy.write_text("{not json at all", encoding="utf-8")
    settings = Settings(api_key=API_KEY, tool_policy_path=policy)

    with caplog.at_level(logging.WARNING):
        tools = await build_server(settings).list_tools()

    assert tools == []
    assert "unreadable tool policy" in caplog.text.lower()


async def test_a_file_holding_something_other_than_an_object_is_ignored(
    tmp_path: Path,
) -> None:
    policy = tmp_path / "tools.json"
    policy.write_text('["get_profile"]', encoding="utf-8")

    assert ToolPolicy(policy).enabled("get_profile") is False


async def test_the_file_is_re_read_rather_than_remembered(tmp_path: Path) -> None:
    """Edited while the server runs, it takes effect on the next question."""
    policy = write(tmp_path / "tools.json", {"get_profile": True})
    store = ToolPolicy(policy)

    assert store.enabled("get_profile") is True
    write(policy, {"get_profile": False})

    assert store.enabled("get_profile") is False


def test_a_policy_knows_whether_it_has_a_file_at_all(tmp_path: Path) -> None:
    """Told apart from a file that exists and enables nothing."""
    assert ToolPolicy(tmp_path / "absent.json").exists() is False
    assert ToolPolicy(write(tmp_path / "there.json", {})).exists() is True


# -- presets write files, they are not consulted --------------------------


def test_the_read_only_preset_keeps_exactly_the_reading_tools() -> None:
    flags = preset("read-only")

    assert set(flags) == set(known_tools())
    for name, meta in known_tools().items():
        assert flags[name] is (meta.access == "read"), name


def test_the_write_preset_turns_on_everything_reversible() -> None:
    flags = preset("write")

    assert set(flags) == set(known_tools())
    for name, meta in known_tools().items():
        assert flags[name] is not meta.irreversible, name


def test_the_irreversible_preset_turns_on_everything() -> None:
    """The third step, and the only one that reaches deleting and booking."""
    assert set(preset("irreversible").values()) == {True}


def test_only_the_third_preset_reaches_an_irreversible_tool() -> None:
    """Its own step because it is its own decision.

    Nothing ships with such an effect yet, so this holds the rule rather than
    a tool: the first `delete_*` will not arrive through `write`.
    """
    for kind in ("read-only", "write"):
        flags = preset(kind)  # type: ignore[arg-type]
        for name, meta in known_tools().items():
            if meta.irreversible:
                assert flags[name] is False, f"{kind} enabled {name}"


def test_each_preset_contains_the_one_before_it() -> None:
    """Three steps, so each has to be a superset of the last."""
    read_only = {n for n, on in preset("read-only").items() if on}
    write = {n for n, on in preset("write").items() if on}
    everything = {n for n, on in preset("irreversible").items() if on}

    assert read_only < write or read_only == write
    assert write <= everything
    assert everything == set(known_tools())


def test_an_unknown_preset_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown preset"):
        preset("everything-plus")  # type: ignore[arg-type]


def test_saving_writes_every_tool_not_only_the_enabled_ones(tmp_path: Path) -> None:
    """The file is an inventory. A reader should not have to guess at gaps."""
    policy = ToolPolicy(tmp_path / "nested" / "tools.json")

    policy.save({"get_profile": True})

    stored = json.loads((tmp_path / "nested" / "tools.json").read_text())
    assert set(stored) == set(known_tools())
    assert stored["get_profile"] is True
    assert stored["search_contacts"] is False


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


@pytest.mark.parametrize("choice", ["read-only", "write", "irreversible"])
def test_every_preset_can_be_written_to_a_named_file(
    choice: str, tmp_path: Path
) -> None:
    """The path is given with the preset, for all three of them."""
    policy = tmp_path / "elsewhere" / f"{choice}.json"

    main(["--tools", choice, "--tools-file", str(policy)])

    stored = json.loads(policy.read_text())
    assert set(stored) == set(known_tools())
    assert stored["get_profile"] is True


def test_the_named_file_beats_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command line is the more deliberate of the two, so it wins."""
    ignored = tmp_path / "from-env.json"
    wanted = tmp_path / "from-argv.json"
    monkeypatch.setenv("LXO_MCP_TOOL_POLICY", str(ignored))

    main(["--tools", "read-only", "--tools-file", str(wanted)])

    assert wanted.is_file()
    assert not ignored.exists()


def test_the_command_line_writes_a_file_even_where_none_existed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The registry is filled as tools are defined, not as they are registered.

    With no file, nothing is registered at all - so a command that had to read
    the registered tools would write an empty file and lock the installation
    out of its own configuration.
    """
    policy = tmp_path / "fresh" / "tools.json"
    monkeypatch.setenv("LXO_MCP_TOOL_POLICY", str(policy))

    main(["--tools", "write"])

    assert set(json.loads(policy.read_text())) == set(known_tools())


def test_a_target_that_is_not_a_file_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A directory where a file was meant is a typo, not a crash.

    It used to reach `save` and come back as a PermissionError traceback,
    which says nothing a person can act on.
    """
    with pytest.raises(SystemExit) as excinfo:
        main(["--tools", "write", "--tools-file", str(tmp_path)])

    assert excinfo.value.code == 2
    assert "Not a file" in capsys.readouterr().err


def test_a_missing_directory_is_created(tmp_path: Path) -> None:
    """Naming somewhere new should not need a mkdir first."""
    policy = tmp_path / "does" / "not" / "exist" / "tools.json"

    main(["--tools", "read-only", "--tools-file", str(policy)])

    assert policy.is_file()


def test_writing_a_preset_replaces_what_was_edited_by_hand(tmp_path: Path) -> None:
    """The presets overwrite. Worth a test, because it loses work.

    Someone who has switched twelve tools off and then runs --tools write to
    pick up a newly added one gets all twelve back.
    """
    policy = tmp_path / "tools.json"
    policy.write_text('{"get_profile": true}', encoding="utf-8")

    main(["--tools", "write", "--tools-file", str(policy)])

    assert len(json.loads(policy.read_text())) == len(known_tools())


async def test_switching_a_tool_off_takes_effect_without_a_restart(
    tmp_path: Path,
) -> None:
    """Measured 2026-08-21, and the half of the story that is instant.

    The call gate reads the file every time, so a tool that has just been
    switched off is refused - even though it stays in a list the client
    already holds.
    """
    policy = write(tmp_path / "tools.json", {"get_profile": True})
    server = build_server(Settings(api_key=API_KEY, tool_policy_path=policy))

    assert [t.name for t in await server.list_tools()] == ["get_profile"]
    write(policy, {"get_profile": False})

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("get_profile", {})

    assert "not enabled" in str(excinfo.value)


async def test_switching_a_tool_on_does_not(tmp_path: Path) -> None:
    """The other half. Registration happens once, when the server is built.

    Pinned as it is rather than as it should be: this falls out of the
    registration time, it was not chosen, and nothing here argues it is right.
    """
    policy = write(tmp_path / "tools.json", {"get_profile": True})
    server = build_server(Settings(api_key=API_KEY, tool_policy_path=policy))

    write(policy, {"get_profile": True, "search_contacts": True})

    assert [t.name for t in await server.list_tools()] == ["get_profile"]
