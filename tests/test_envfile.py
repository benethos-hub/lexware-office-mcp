"""Editing a ``.env`` a person keeps by hand, without ruining it."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from benethos_lexware_office_mcp import envfile
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


def test_a_byte_order_mark_does_not_hide_the_first_key(tmp_path: Path) -> None:
    """Notepad writes one, and it used to become part of LXO_MCP_API_KEY."""
    path = tmp_path / ".env"
    path.write_bytes(b"\xef\xbb\xbfLXO_MCP_API_KEY=from-notepad\nLXO_MCP_RATE=1\n")

    assert read_env_file(path) == {
        "LXO_MCP_API_KEY": "from-notepad",
        "LXO_MCP_RATE": "1",
    }


def test_updating_a_file_with_a_byte_order_mark_rewrites_its_first_key(
    tmp_path: Path,
) -> None:
    """Not a second LXO_MCP_API_KEY appended below the hidden one."""
    path = tmp_path / ".env"
    path.write_bytes(b"\xef\xbb\xbfLXO_MCP_API_KEY=old\n")

    update_env_file(path, {"LXO_MCP_API_KEY": "new"})

    assert path.read_bytes() == b"LXO_MCP_API_KEY=new\n"


def test_a_key_that_appears_twice_is_rewritten_both_times(tmp_path: Path) -> None:
    """The reader takes the last occurrence. Rewriting only the first meant
    the interface reported a checked key the server never read."""
    path = tmp_path / ".env"
    path.write_text(
        "LXO_MCP_API_KEY=first\n# later\nLXO_MCP_API_KEY=second\n", encoding="utf-8"
    )

    update_env_file(path, {"LXO_MCP_API_KEY": "new"})

    assert read_env_file(path) == {"LXO_MCP_API_KEY": "new"}
    assert "first" not in path.read_text(encoding="utf-8")
    assert "second" not in path.read_text(encoding="utf-8")


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


@pytest.mark.parametrize(
    "value", ["x\nLXO_MCP_API_KEY=planted", "x\rY=1", "x Y=1", "x\x0cY=1", "x\x00"]
)
def test_a_line_break_in_a_value_is_refused(tmp_path: Path, value: str) -> None:
    """Written as given, it would end the line and start a setting of its own."""
    path = tmp_path / ".env"
    path.write_text("LXO_MCP_PAGE_SIZE=50\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line break") as excinfo:
        update_env_file(path, {"LXO_MCP_DOWNLOAD_DIR": value})

    assert "planted" not in str(excinfo.value)
    assert path.read_text(encoding="utf-8") == "LXO_MCP_PAGE_SIZE=50\n"


def test_a_line_break_in_a_key_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="line break"):
        update_env_file(tmp_path / ".env", {"A\nB": "1"})


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_a_new_file_is_readable_by_its_owner_only(tmp_path: Path) -> None:
    """It holds the API key."""
    path = tmp_path / ".env"

    update_env_file(path, {"LXO_MCP_API_KEY": "secret"})

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_an_existing_file_keeps_its_permissions(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("A=1\n", encoding="utf-8")
    path.chmod(0o640)

    update_env_file(path, {"A": "2"})

    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_nothing_but_the_file_is_left_behind(tmp_path: Path) -> None:
    """Written beside it and moved into place, with no temporary file after."""
    path = tmp_path / ".env"
    path.write_text("A=1\n", encoding="utf-8")

    update_env_file(path, {"A": "2"})

    assert [p.name for p in tmp_path.iterdir()] == [".env"]


def test_a_failed_write_leaves_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".env"
    path.write_text("A=1\n", encoding="utf-8")

    def full_disk(*_args: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(envfile.os, "replace", full_disk)

    with pytest.raises(OSError):
        update_env_file(path, {"A": "2"})

    assert path.read_text(encoding="utf-8") == "A=1\n"
    assert [p.name for p in tmp_path.iterdir()] == [".env"]


def test_the_server_and_the_interface_read_with_the_same_parser() -> None:
    """One parser, so a displayed value cannot differ from a read one."""
    from benethos_lexware_office_mcp import config

    assert config._parse_env_file is read_env_file
