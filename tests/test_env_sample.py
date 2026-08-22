"""The settings sample that ships in the package, and the `.env` search.

The sample is documentation that can go stale, so these tests treat it as
code: it must parse, it must leave the safe defaults in place, and it must
mention every setting the loader actually reads.
"""

from __future__ import annotations

import re
from pathlib import Path

from benethos_lexware_office_mcp.config import (
    _env_lookup,
    _parse_env_file,
    load_settings,
    settings_sample,
)

SAMPLE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "benethos_lexware_office_mcp"
    / "env.sample"
)

# Every variable `load_settings` looks up. Adding one here without adding it to
# the sample fails the drift test below.
SETTINGS = {
    "LXO_MCP_API_KEY",
    "LXO_MCP_TOOL_POLICY",
    "LXO_MCP_BASE_URL",
    "LXO_MCP_APP_BASE_URL",
    "LXO_MCP_DOWNLOAD_DIR",
    "LXO_MCP_TIMEOUT",
    "LXO_MCP_RATE",
    "LXO_MCP_BURST",
    "LXO_MCP_PAGE_SIZE",
    "LXO_MCP_LOG_LEVEL",
    "LXO_MCP_TRANSPORT",
    "LXO_MCP_BEARER_TOKEN",
    "LXO_MCP_HTTP_HOST",
    "LXO_MCP_HTTP_PORT",
    "LXO_MCP_HTTP_PATH",
    "LXO_MCP_ALLOWED_HOSTS",
    "LXO_MCP_EXIT_ON_CONFIG_CHANGE",
    "LXO_MCP_GENERATE_BEARER_TOKEN",
}


def test_the_sample_is_committed() -> None:
    assert SAMPLE.is_file()


def test_the_sample_ships_with_the_package() -> None:
    """A wheel has no `config/` beside it, so this is the only copy a user gets."""
    assert settings_sample() == SAMPLE.read_text(encoding="utf-8")


def test_the_sample_says_how_to_get_it_out_of_an_installed_copy() -> None:
    assert "--settings-sample" in settings_sample()


def test_only_the_api_key_is_active_everything_else_is_commented() -> None:
    assert _parse_env_file(SAMPLE) == {"LXO_MCP_API_KEY": ""}


def test_copying_the_sample_enables_nothing_by_itself() -> None:
    """Someone who fills in only the key must not accidentally enable writes.

    The sample cannot enable a tool at all any more - that is the policy
    file's business - so what it must not do is name one.
    """
    settings = load_settings(_parse_env_file(SAMPLE))
    assert settings.api_key is None
    assert settings.tool_policy_path is None


def test_sample_documents_every_setting_the_loader_reads() -> None:
    mentioned = set(re.findall(r"LXO_MCP_[A-Z_]+", settings_sample()))
    assert SETTINGS <= mentioned, f"missing from the sample: {SETTINGS - mentioned}"


def test_sample_holds_no_key() -> None:
    """It is committed, so an accidental real key here would be published."""
    assert _parse_env_file(SAMPLE)["LXO_MCP_API_KEY"] == ""


def test_sample_warns_that_the_copy_holds_a_credential() -> None:
    text = settings_sample()
    assert "credential" in text
    assert "version control" in text


def test_config_directory_is_searched(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text("LXO_MCP_PAGE_SIZE=7\n", encoding="utf-8")
    assert _env_lookup(cwd=tmp_path)["LXO_MCP_PAGE_SIZE"] == "7"


def test_working_directory_env_beats_the_config_directory(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text("LXO_MCP_PAGE_SIZE=7\n", encoding="utf-8")
    (tmp_path / ".env").write_text("LXO_MCP_PAGE_SIZE=9\n", encoding="utf-8")
    assert _env_lookup(cwd=tmp_path)["LXO_MCP_PAGE_SIZE"] == "9"


def test_the_typing_marker_sits_beside_the_code() -> None:
    """Without it a type checker ignores every annotation this package has.

    Asserted here rather than only in the release workflow, because a file
    that exists is not a file that ships: the sample beside this one was not
    in the wheel until the release commit moved it in, and no test had
    anything to say about that.
    """
    marker = SAMPLE.parent / "py.typed"

    assert marker.is_file(), "py.typed is what makes the annotations visible"
    assert marker.read_bytes() == b"", "PEP 561 wants the marker empty"
