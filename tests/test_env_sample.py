"""The settings sample that ships in the package, and the `.env` search.

The sample is documentation that can go stale, so these tests treat it as
code: it must parse, it must leave the safe defaults in place, and it must
mention every setting the loader actually reads.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from benethos_lexware_office_mcp import settings as settings_module
from benethos_lexware_office_mcp.settings import _env_lookup, load_settings
from benethos_lexware_office_mcp.settings.envfile import read_env_file
from benethos_lexware_office_mcp.settings.locations import settings_sample

SAMPLE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "benethos_lexware_office_mcp"
    / "env.sample"
)

# Every variable `load_settings` looks up, read from its source: each one is a
# `get("NAME")` there. A list kept by hand beside it had already fallen behind
# by two, so the sample drifted with the test still green.
_LOADER = Path(settings_module.__file__).read_text(encoding="utf-8")
SETTINGS = {f"LXO_MCP_{name}" for name in re.findall(r'\bget\("([A-Z_]+)"\)', _LOADER)}


def test_the_sample_is_committed() -> None:
    assert SAMPLE.is_file()


def test_the_sample_ships_with_the_package() -> None:
    """A wheel has no `config/` beside it, so this is the only copy a user gets."""
    assert settings_sample() == SAMPLE.read_text(encoding="utf-8")


def test_the_sample_says_how_to_get_it_out_of_an_installed_copy() -> None:
    assert "--settings-sample" in settings_sample()


def test_only_the_api_key_is_active_everything_else_is_commented() -> None:
    assert read_env_file(SAMPLE) == {"LXO_MCP_API_KEY": ""}


def test_copying_the_sample_enables_nothing_by_itself() -> None:
    """Someone who fills in only the key must not accidentally enable writes.

    The sample cannot enable a tool at all any more - that is the policy
    file's business - so what it must not do is name one.
    """
    settings = load_settings(read_env_file(SAMPLE))
    assert settings.api_key is None
    assert settings.tool_policy_path is None


def test_the_names_are_read_from_the_loader() -> None:
    """A pattern that matched nothing would pass the test below vacuously."""
    assert {"LXO_MCP_API_KEY", "LXO_MCP_LISTED_DOWNLOADS"} <= SETTINGS
    assert len(SETTINGS) >= 20


def test_sample_documents_every_setting_the_loader_reads() -> None:
    mentioned = set(re.findall(r"LXO_MCP_[A-Z_]+", settings_sample()))
    assert SETTINGS <= mentioned, f"missing from the sample: {SETTINGS - mentioned}"


def test_sample_holds_no_key() -> None:
    """It is committed, so an accidental real key here would be published."""
    assert read_env_file(SAMPLE)["LXO_MCP_API_KEY"] == ""


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


@pytest.mark.parametrize("document", ["README.md", "SPECS.md"])
def test_every_setting_has_a_row_in_the_settings_table(document: str) -> None:
    """The sample is not the only list: both documents keep a table of them.

    SPECS section 7 went without the eight HTTP settings from 0.2.0 on, and
    nothing noticed, because nothing compared.
    """
    text = (Path(__file__).resolve().parents[1] / document).read_text(encoding="utf-8")
    rows = set(re.findall(r"^\| `(LXO_MCP_[A-Z_]+)` \|", text, re.MULTILINE))
    assert SETTINGS - rows == set(), f"no row in {document}"
    assert rows - SETTINGS == set(), f"a row in {document} for nothing the loader reads"
