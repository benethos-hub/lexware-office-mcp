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
    Settings,
    load_settings,
)
from benethos_lexware_office_mcp.errors import ConfigError


def test_defaults_are_safe() -> None:
    settings = load_settings({})
    assert settings.mode == "read"
    assert settings.api_key is None
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
            "LXO_MCP_MODE": "write",
            "LXO_MCP_BASE_URL": "https://example.invalid/",
            "LXO_MCP_RATE": "0.5",
            "LXO_MCP_BURST": "4",
            "LXO_MCP_PAGE_SIZE": "10",
            "LXO_MCP_TIMEOUT": "5",
        }
    )
    assert settings.api_key == "key-0123456789"
    assert settings.mode == "write"
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
        {"LXO_MCP_MODE": "admin"},
        {"LXO_MCP_RATE": "not-a-number"},
        {"LXO_MCP_RATE": "0"},
        {"LXO_MCP_BURST": "0"},
        {"LXO_MCP_TIMEOUT": "-1"},
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


def test_env_file_is_read_but_real_environment_wins(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "# a comment\nLXO_MCP_API_KEY='from-file-123456'\nexport LXO_MCP_MODE=write\n",
        encoding="utf-8",
    )
    from benethos_lexware_office_mcp.config import _env_lookup

    merged = _env_lookup(cwd=tmp_path)
    assert merged["LXO_MCP_API_KEY"] == "from-file-123456"
    assert merged["LXO_MCP_MODE"] == "write"


def test_malformed_env_file_lines_are_ignored(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "this line has no equals sign\nLXO_MCP_PAGE_SIZE=5\n", encoding="utf-8"
    )
    from benethos_lexware_office_mcp.config import _parse_env_file

    assert _parse_env_file(tmp_path / ".env") == {"LXO_MCP_PAGE_SIZE": "5"}


def test_missing_env_file_is_not_an_error(tmp_path: Path) -> None:
    from benethos_lexware_office_mcp.config import _parse_env_file

    assert _parse_env_file(tmp_path / "absent.env") == {}
