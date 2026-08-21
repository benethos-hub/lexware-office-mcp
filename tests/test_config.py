"""Settings resolution. No real environment and no config directory involved."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_lexware_office_mcp.config import (
    DEFAULT_APP_BASE_URL,
    DEFAULT_BASE_URL,
    DEFAULT_BURST,
    DEFAULT_PAGE_SIZE,
    DEFAULT_RATE,
    MAX_PAGE_SIZE,
    Settings,
    load_settings,
)
from benethos_lexware_office_mcp.errors import ConfigError


def test_defaults_are_safe() -> None:
    settings = load_settings({})
    assert settings.api_key is None
    assert settings.tool_policy_path is None
    assert settings.base_url == DEFAULT_BASE_URL
    assert settings.app_base_url == DEFAULT_APP_BASE_URL
    assert settings.page_size == DEFAULT_PAGE_SIZE


def test_rate_default_stays_below_the_documented_ceiling() -> None:
    """The API allows 2 per second and warns against aiming exactly at it."""
    settings = load_settings({})
    assert settings.rate < 2.0
    assert settings.rate == DEFAULT_RATE
    assert settings.burst == DEFAULT_BURST


def test_environment_overrides_defaults() -> None:
    settings = load_settings(
        {
            "LXO_MCP_API_KEY": "key-0123456789",
            "LXO_MCP_TOOL_POLICY": "/somewhere/tools.json",
            "LXO_MCP_BASE_URL": "https://example.invalid/",
            "LXO_MCP_RATE": "0.5",
            "LXO_MCP_BURST": "4",
            "LXO_MCP_PAGE_SIZE": "10",
            "LXO_MCP_TIMEOUT": "5",
        }
    )
    assert settings.api_key == "key-0123456789"
    assert settings.tool_policy_path == Path("/somewhere/tools.json")
    assert settings.rate == 0.5
    assert settings.burst == 4
    assert settings.page_size == 10
    assert settings.timeout == 5.0


def test_trailing_slash_is_stripped_from_urls() -> None:
    """So that joining a path never produces a double slash."""
    settings = load_settings({"LXO_MCP_BASE_URL": "https://example.invalid/"})
    assert settings.base_url == "https://example.invalid"


@pytest.mark.parametrize(
    "env",
    [
        {"LXO_MCP_RATE": "not-a-number"},
        {"LXO_MCP_RATE": "0"},
        {"LXO_MCP_BURST": "0"},
        {"LXO_MCP_TIMEOUT": "-1"},
        {"LXO_MCP_PAGE_SIZE": "251"},
    ],
)
def test_invalid_values_are_rejected(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        load_settings(env)


def test_unknown_log_level_falls_back_rather_than_failing() -> None:
    """A bad log level must not stop the server from starting."""
    assert load_settings({"LXO_MCP_LOG_LEVEL": "LOUD"}).log_level == "INFO"


def test_missing_api_key_explains_where_to_get_one() -> None:
    with pytest.raises(ConfigError) as excinfo:
        Settings().require_api_key()
    assert "LXO_MCP_API_KEY" in str(excinfo.value)


def test_env_file_is_read_but_real_environment_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both halves of the claim, against a controlled environment.

    The real ``os.environ`` is replaced rather than read. A developer with
    ``LXO_MCP_MODE`` set in their own shell would otherwise flip the answer,
    and the assertion would be about their machine instead of about the
    precedence rule. The second half was missing entirely: the name promised
    that the environment wins and only the file was ever checked.
    """
    from benethos_lexware_office_mcp import config as C

    (tmp_path / ".env").write_text(
        "# a comment\nLXO_MCP_API_KEY='from-file-123456'\nexport LXO_MCP_MODE=write\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(C, "_project_config_dir", lambda: None)
    monkeypatch.setattr(C, "config_dir", lambda: tmp_path / "absent")

    monkeypatch.setattr(C.os, "environ", {})
    from_file = C._env_lookup(cwd=tmp_path)
    assert from_file["LXO_MCP_API_KEY"] == "from-file-123456"
    assert from_file["LXO_MCP_MODE"] == "write"

    monkeypatch.setattr(C.os, "environ", {"LXO_MCP_MODE": "read"})
    overridden = C._env_lookup(cwd=tmp_path)
    assert overridden["LXO_MCP_MODE"] == "read", "the file beat the environment"
    assert overridden["LXO_MCP_API_KEY"] == "from-file-123456"


def test_malformed_env_file_lines_are_ignored(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "this line has no equals sign\nLXO_MCP_PAGE_SIZE=5\n", encoding="utf-8"
    )
    from benethos_lexware_office_mcp.config import _parse_env_file

    assert _parse_env_file(tmp_path / ".env") == {"LXO_MCP_PAGE_SIZE": "5"}


def test_missing_env_file_is_not_an_error(tmp_path: Path) -> None:
    from benethos_lexware_office_mcp.config import _parse_env_file

    assert _parse_env_file(tmp_path / "absent.env") == {}


def test_page_size_may_go_up_to_the_upstream_maximum() -> None:
    """251 is rejected by the API itself, so 250 must still be accepted here."""
    assert load_settings({"LXO_MCP_PAGE_SIZE": "250"}).page_size == MAX_PAGE_SIZE


def test_the_pdf_page_default_is_configurable() -> None:
    assert load_settings({"LXO_MCP_PDF_PAGES": "3"}).pdf_pages == 3


def test_the_pdf_page_default_is_not_the_list_page_size() -> None:
    """Two settings about pages, and confusing them would be easy.

    `LXO_MCP_PAGE_SIZE` is rows per page of a search result.
    `LXO_MCP_PDF_PAGES` is how much of a document gets rendered. Neither may
    quietly answer for the other.
    """
    settings = load_settings({"LXO_MCP_PAGE_SIZE": "50", "LXO_MCP_PDF_PAGES": "3"})
    assert settings.page_size == 50
    assert settings.pdf_pages == 3


def test_a_nonsense_pdf_page_count_is_refused_at_startup() -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_settings({"LXO_MCP_PDF_PAGES": "nope"})
    assert "LXO_MCP_PDF_PAGES" in str(excinfo.value)
