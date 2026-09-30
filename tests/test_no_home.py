"""A process in which no home directory resolves.

platformdirs raises from 4.12 on when ``HOME`` is unset or empty and the uid
has no password database entry, as under ``env -i`` with a foreign uid. It
used to answer a relative ``~/.config/...`` instead. Either way there is no
per-user directory, and what matters is that the server says what to set
rather than ending in a traceback - and that nothing which does not need that
directory stops working.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from benethos_lexware_office_mcp import settings as C
from benethos_lexware_office_mcp.cli import main
from benethos_lexware_office_mcp.configui import pages, probe
from benethos_lexware_office_mcp.configui.state import Installation
from benethos_lexware_office_mcp.errors import ConfigError
from benethos_lexware_office_mcp.files import storage
from benethos_lexware_office_mcp.server import build_server
from benethos_lexware_office_mcp.settings import Settings
from benethos_lexware_office_mcp.settings import locations as L


def _no_home(*_args: object, **_kwargs: object) -> str:
    raise RuntimeError("could not determine home directory")


@pytest.fixture
def homeless(monkeypatch: pytest.MonkeyPatch) -> None:
    """platformdirs as it answers without a home, and no checkout config."""
    monkeypatch.setattr(L, "user_config_dir", _no_home)
    monkeypatch.setattr(L, "user_cache_dir", _no_home)
    monkeypatch.setattr(L, "_project_config_dir", lambda: None)
    for key in [k for k in os.environ if k.startswith("LXO_MCP_")]:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.usefixtures("homeless")
def test_the_config_directory_says_what_to_set() -> None:
    with pytest.raises(ConfigError) as excinfo:
        L.config_dir()

    message = str(excinfo.value)
    assert "HOME" in message and "--env-file" in message
    assert "~" not in message and "/" not in message


@pytest.mark.usefixtures("homeless")
def test_the_download_directory_says_what_to_set() -> None:
    with pytest.raises(ConfigError) as excinfo:
        L.download_dir()

    assert "LXO_MCP_DOWNLOAD_DIR" in str(excinfo.value)


@pytest.mark.usefixtures("homeless")
def test_a_download_names_the_setting_instead_of_writing_below_the_cwd() -> None:
    """A tool error, which the model reads and can pass on."""
    with pytest.raises(ConfigError, match="LXO_MCP_DOWNLOAD_DIR"):
        storage.directory_for(Settings())


@pytest.mark.usefixtures("homeless")
def test_a_named_download_directory_needs_no_home(tmp_path: Path) -> None:
    target = tmp_path / "downloads"

    assert storage.directory_for(Settings(download_path=target)) == target


@pytest.mark.usefixtures("homeless")
def test_the_other_places_are_still_searched(tmp_path: Path) -> None:
    """A working directory or a checkout needs no home."""
    (tmp_path / ".env").write_text("LXO_MCP_PAGE_SIZE=7\n", encoding="utf-8")

    assert L.config_candidates(".env", cwd=tmp_path) == [
        tmp_path / "config" / ".env",
        tmp_path / ".env",
    ]
    assert L.resolve_config_file(".env", cwd=tmp_path) == tmp_path / ".env"
    assert C.load_settings(cwd=tmp_path).page_size == 7


@pytest.mark.usefixtures("homeless")
def test_with_no_file_anywhere_there_is_nowhere_to_create_one(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="HOME"):
        L.resolve_config_file("tools.json", cwd=tmp_path)


@pytest.mark.usefixtures("homeless")
def test_settings_can_still_come_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No file is not an error, with or without a home."""
    monkeypatch.setenv("LXO_MCP_API_KEY", "k")

    assert L.env_file_in_effect(cwd=tmp_path) is None
    assert C.load_settings(cwd=tmp_path).api_key == "k"


@pytest.mark.usefixtures("homeless")
def test_a_server_with_a_named_policy_starts(tmp_path: Path) -> None:
    """Nothing to publish as a resource, which is not a reason to fail."""
    policy = tmp_path / "tools.json"
    policy.write_text('{"get_profile": true}', encoding="utf-8")

    server = build_server(Settings(api_key="k", tool_policy_path=policy))

    assert server is not None


@pytest.mark.usefixtures("homeless")
def test_the_command_line_ends_in_one_line_not_a_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    # The suite hands every test a policy file of its own. This one needs the
    # search, which is where the missing home is found.
    monkeypatch.setattr(
        L, "tool_policy_file", lambda: L.resolve_config_file(L.TOOL_POLICY_NAME)
    )

    with pytest.raises(SystemExit) as excinfo:
        main(["--tools", "show", "--log-level", "ERROR"])

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "", "stdout carries the JSON-RPC stream"
    assert "HOME" in captured.err and "--tools-file" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.usefixtures("homeless")
def test_the_pages_render_and_say_why_there_is_no_download_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "_last", None)
    env = tmp_path / ".env"
    env.write_text("LXO_MCP_PAGE_SIZE=50\n", encoding="utf-8")
    inst = Installation(
        settings=Settings(tool_policy_path=tmp_path / "tools.json"),
        env_path=env,
        cwd=tmp_path,
    )

    overview = pages.overview(inst).decode("utf-8")
    credentials = pages.credentials(inst).decode("utf-8")

    assert "LXO_MCP_DOWNLOAD_DIR, or HOME" in overview
    assert "Zugangsdaten" in credentials
