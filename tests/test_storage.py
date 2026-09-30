"""Where a download lands on disk: the name it gets, and what is never overwritten."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.files import storage
from helpers import (
    PDF,
)


def response_with(disposition: str) -> httpx.Response:
    return httpx.Response(
        200, content=PDF, headers={"content-disposition": disposition}
    )


def test_the_servers_filename_is_used_when_it_is_ordinary() -> None:
    name = storage.suggested_name(
        response_with("inline; filename=invoice-2026-014.pdf;"), "fallback.pdf"
    )
    assert name == "invoice-2026-014.pdf"


def test_a_filename_that_is_a_path_is_reduced_to_its_last_part() -> None:
    """Content-Disposition is written by the server, so it is untrusted."""
    name = storage.suggested_name(
        response_with('attachment; filename="../../../etc/passwd"'), "fallback.pdf"
    )
    assert name == "passwd"
    assert "/" not in name


def test_a_windows_path_is_stripped_too() -> None:
    """The separator that matters is not always the platform's own."""
    name = storage.suggested_name(
        response_with(
            'attachment; filename="..\\\\..\\\\windows\\\\system32\\\\x.pdf"'
        ),
        "fallback.pdf",
    )
    assert name == "x.pdf"
    assert "\\" not in name


def test_unusual_characters_are_replaced() -> None:
    """A filename that reaches the disk should be boring."""
    name = storage.suggested_name(
        response_with('attachment; filename="Rechnung 2026 (final) & copy.pdf"'),
        "f.pdf",
    )
    assert all(c.isalnum() or c in "._-" for c in name), name
    assert name.endswith(".pdf")


@pytest.mark.parametrize(
    "name", ["CON.pdf", "con.pdf", "NUL", "com1.xml", "LPT9.pdf", "aux.tar.gz"]
)
def test_a_windows_device_name_is_not_used_as_is(name: str) -> None:
    """On Windows `CON.pdf` is the console, not a file."""
    cleaned = storage.suggested_name(
        response_with(f'attachment; filename="{name}"'), "f.pdf"
    )

    assert cleaned.split(".")[0].upper() not in storage._DEVICES
    assert cleaned.endswith(name)


def test_a_name_that_merely_starts_like_a_device_is_left_alone() -> None:
    name = storage.suggested_name(
        response_with('attachment; filename="CONTRACT.pdf"'), "f.pdf"
    )
    assert name == "CONTRACT.pdf"


def test_a_useless_filename_falls_back_to_the_callers_own() -> None:
    assert storage.suggested_name(
        response_with('attachment; filename=".."'), "f.pdf"
    ) == ("f.pdf")
    assert storage.suggested_name(httpx.Response(200, content=PDF), "f.pdf") == "f.pdf"


def test_a_download_never_replaces_an_existing_file(tmp_path: Path) -> None:
    """Overwriting last month's invoice with this month's is worse than failing."""
    first = storage.save(b"one", "invoice.pdf", tmp_path)
    second = storage.save(b"two", "invoice.pdf", tmp_path)

    assert first.name == "invoice.pdf"
    assert second.name == "invoice-2.pdf"
    assert first.read_bytes() == b"one"
    assert second.read_bytes() == b"two"


def test_the_download_directory_is_created(tmp_path: Path) -> None:
    target = tmp_path / "not" / "there" / "yet"
    assert storage.directory_for(Settings(download_path=target)) == target
    assert target.is_dir()


def test_a_name_taken_between_the_check_and_the_write_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another download claims the name after it looked free. The file it
    wrote survives, and this one moves to the next name."""
    real_open = Path.open

    def racing_open(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if self.name == "invoice.pdf" and "x" in mode and not self.exists():
            self.write_bytes(b"the other download")
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", racing_open)

    saved = storage.save(b"this download", "invoice.pdf", tmp_path)

    assert saved.name == "invoice-2.pdf"
    assert (tmp_path / "invoice.pdf").read_bytes() == b"the other download"
    assert saved.read_bytes() == b"this download"


def test_reusing_a_copy_that_already_carries_a_counter(tmp_path: Path) -> None:
    """The match may be behind a name that was itself pushed aside once."""
    storage.save(b"january", "invoice.pdf", tmp_path)
    numbered = storage.save(b"february", "invoice.pdf", tmp_path)

    again = storage.save(b"february", "invoice.pdf", tmp_path)

    assert again == numbered
    assert len(list(tmp_path.iterdir())) == 2


@pytest.mark.parametrize("name", ["../outside.pdf", "..%2Foutside.pdf", ".."])
def test_resolve_never_leaves_the_directory(tmp_path: Path, name: str) -> None:
    inside = tmp_path / "downloads"
    inside.mkdir()
    (tmp_path / "outside.pdf").write_bytes(PDF)

    assert storage.resolve(name, inside) is None
