"""The captured shapes carry no record out of the account.

`api_shape.py` reads a live account and writes what it saw into a versioned
file. That is only safe while the file holds names and types rather than
values, so the rule is checked here rather than left to whoever runs it.

Offline: these tests read files in the repository and never touch the network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SHAPES = Path(__file__).resolve().parent / "api-shapes"

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# A date, which would say when a record was written, and an IBAN, which would
# be somebody's bank account. Neither is a shape.
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")


def captures() -> list[Path]:
    """Every capture, and never an empty list.

    A guard that loops over nothing passes without checking anything, which
    is the hole SPECS.md section 14.1 names: a test that reports green for
    work it did not do. So the absence of captures fails here rather than
    quietly disarming the three checks below.
    """
    found = sorted(SHAPES.glob("shape-*.txt"))
    assert found, f"no capture in {SHAPES.name}, so nothing below checks anything"
    return found


def test_the_directory_explains_itself() -> None:
    """A directory of generated files needs to say what generated them."""
    readme = SHAPES / "README.md"
    assert readme.is_file()
    assert "api_shape.py" in readme.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "pattern", [UUID, EMAIL, DATE, IBAN], ids=["uuid", "email", "date", "iban"]
)
def test_no_capture_carries_a_record_out_of_the_account(
    pattern: re.Pattern[str],
) -> None:
    """The one rule that makes these files safe to version.

    An id, an address or a date is a record rather than a shape, and section
    11 of SPECS.md keeps all three out of versioned files. A capture that
    picked one up would be a leak that no review is likely to catch, because
    the files are long and look alike.
    """
    for capture in captures():
        found = pattern.findall(capture.read_text(encoding="utf-8"))
        assert not found, f"{capture.name} carries {found[:3]}"


def test_a_capture_records_types_rather_than_values() -> None:
    """Values appear only where a closed vocabulary is the point.

    Not a count of allowed words - that would turn into a list to be edited
    whenever the API adds a status. The check is that a value line stays a
    short token: a name, an address or a remark would not.
    """
    for capture in captures():
        for line in capture.read_text(encoding="utf-8").splitlines():
            if ": " not in line or "=" not in line:
                continue
            for kind in line.split(": ", 1)[1].split("|"):
                if "=" not in kind:
                    continue
                value = kind.split("=", 1)[1]
                assert len(value) <= 32, (
                    f"{capture.name}: {value!r} is not a vocabulary"
                )
                assert " " not in value, (
                    f"{capture.name}: {value!r} is not a vocabulary"
                )
