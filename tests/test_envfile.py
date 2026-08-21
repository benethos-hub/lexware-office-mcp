"""Editing a ``.env`` a person keeps by hand, without ruining it."""

from __future__ import annotations

from pathlib import Path

from benethos_lexware_office_mcp.envfile import read_env_file, update_env_file


def test_reads_the_forms_a_person_writes(tmp_path: Path) -> None:
    """Quotes, an export prefix, comments and blank lines all appear here."""
    path = tmp_path / ".env"
    path.write_text(
        "# the key\n"
        'LXO_MCP_API_KEY="quoted"\n'
        "\n"
        "export LXO_MCP_RATE=1.5\n"
        "  LXO_MCP_BURST = 3  \n"
        "nonsense without an equals sign\n",
        encoding="utf-8",
    )

    assert read_env_file(path) == {
        "LXO_MCP_API_KEY": "quoted",
        "LXO_MCP_RATE": "1.5",
        "LXO_MCP_BURST": "3",
    }


def test_a_missing_file_is_empty_rather_than_an_error(tmp_path: Path) -> None:
    assert read_env_file(tmp_path / "absent.env") == {}


def test_an_update_keeps_comments_ordering_and_strangers(tmp_path: Path) -> None:
    """The file belongs to the user. Only the named keys may change."""
    path = tmp_path / ".env"
    path.write_text(
        "# how fast to ask\nLXO_MCP_RATE=1.5\n\n# not ours\nSOMETHING_ELSE=keep\n",
        encoding="utf-8",
    )

    update_env_file(path, {"LXO_MCP_RATE": "0.9"})

    assert path.read_text(encoding="utf-8") == (
        "# how fast to ask\nLXO_MCP_RATE=0.9\n\n# not ours\nSOMETHING_ELSE=keep\n"
    )


def test_a_new_key_is_appended(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("LXO_MCP_RATE=1.5\n", encoding="utf-8")

    update_env_file(path, {"LXO_MCP_BURST": "2"})

    assert path.read_text(encoding="utf-8") == "LXO_MCP_RATE=1.5\nLXO_MCP_BURST=2\n"


def test_the_file_and_its_directory_are_created(tmp_path: Path) -> None:
    """An installed copy has neither, and creating them is the point."""
    path = tmp_path / "nested" / "deeper" / ".env"

    update_env_file(path, {"LXO_MCP_API_KEY": "written"})

    assert read_env_file(path) == {"LXO_MCP_API_KEY": "written"}


def test_a_rewritten_key_keeps_its_place_under_its_comment(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("A=1\n# about B\nB=2\nC=3\n", encoding="utf-8")

    update_env_file(path, {"B": "changed"})

    assert path.read_text(encoding="utf-8").splitlines() == [
        "A=1",
        "# about B",
        "B=changed",
        "C=3",
    ]


def test_the_server_and_the_interface_read_with_the_same_parser() -> None:
    """One parser, so a displayed value cannot differ from a read one."""
    from benethos_lexware_office_mcp import config

    assert config._parse_env_file is read_env_file
