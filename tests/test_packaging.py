"""What the package ships, and what the documentation says it is.

Two kinds of thing that break without breaking anything: a file that quietly
stops being packed, and a version quoted as an example that nobody thought to
move at release time.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import benethos_lexware_office_mcp

PACKAGE_DIR = Path(benethos_lexware_office_mcp.__file__).resolve().parent
REPO = PACKAGE_DIR.parents[1]
MARKER = PACKAGE_DIR / "py.typed"


def test_the_typing_marker_sits_beside_the_code() -> None:
    """Without it a type checker skips this package, annotations and all.

    Deleting the file breaks type checking for everyone who imports this
    package, and breaks no test, no import and no build - the loss would be
    silent. Whether it survives into the wheel is a separate question, asked
    in the release workflow, because a file that exists is not a file that
    ships.
    """
    assert MARKER.is_file(), f"{MARKER.name} is what makes the annotations visible"
    assert MARKER.read_bytes() == b"", "PEP 561 wants the marker empty"


# The documentation quotes the current version in four places, each of them an
# example somebody is meant to copy. The failure mode is forgetting at release
# time, not difficulty, so this asserts rather than rewrites: the suite goes
# red until the examples agree with the package.
VERSION_EXAMPLES = (
    # The exact pin the client configuration shows.
    ("README.md", r"benethos-lexware-office-mcp==(\d+\.\d+\.\d+)"),
    # The image tag to pin instead of `:latest`. `:0.2` names a minor line on
    # purpose and has two components, so it is not matched.
    ("README.md", r"`:(\d+\.\d+\.\d+)`"),
    # The status line each document opens with.
    ("README.md", r"\*\*Status: (\d+\.\d+\.\d+)"),
    ("SPECS.md", r"\*\*Status: (\d+\.\d+\.\d+)"),
)


@pytest.mark.parametrize(("relative_path", "pattern"), VERSION_EXAMPLES)
def test_the_documented_version_examples_are_current(
    relative_path: str, pattern: str
) -> None:
    text = (REPO / relative_path).read_text(encoding="utf-8")
    found = re.findall(pattern, text)

    # A pattern that has stopped matching would pass while checking nothing.
    assert found, f"{relative_path} no longer contains {pattern!r}"

    stale = sorted({v for v in found if v != benethos_lexware_office_mcp.__version__})
    assert not stale, (
        f"{relative_path} still shows {stale}, the package is at "
        f"{benethos_lexware_office_mcp.__version__}. Anyone copying that "
        "example uses an older release than the one they are reading about."
    )


def test_the_version_check_would_notice_a_stale_example() -> None:
    """The guard is worth having only if it fires."""
    pattern = r"benethos-lexware-office-mcp==(\d+\.\d+\.\d+)"
    sample = 'uvx "benethos-lexware-office-mcp==0.0.1"'

    found = re.findall(pattern, sample)

    assert found == ["0.0.1"]
    assert found != [benethos_lexware_office_mcp.__version__]
