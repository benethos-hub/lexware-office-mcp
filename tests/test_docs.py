"""The documents under docs/ and the links between them.

`docs/CONCEPT.md` is the overview, and a document that grew too long keeps
its parts in a folder of the same name in lowercase beside it: `concept/`.
The sections keep their numbers across the files, so a reference such as
"section 9.2" is a link to the file that holds it. Rename a heading or move
a section and such a link still renders, it just lands nowhere. See
CLAUDE.md, "Documentation".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from test_readme import _anchors, _link_targets

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"

# Every Markdown file that links into docs/ or within it. The README is not
# among them: PyPI renders it alone, and test_readme.py holds it to absolute
# links instead.
LINKING = sorted(
    [*DOCS.rglob("*.md"), REPO / "CLAUDE.md", REPO / "live" / "shapes" / "README.md"]
)


def _relative_targets(path: Path) -> list[str]:
    return [
        target
        for target in _link_targets(path.read_text(encoding="utf-8"))
        if not target.startswith(("http://", "https://", "mailto:"))
    ]


@pytest.mark.parametrize("path", LINKING, ids=lambda p: p.relative_to(REPO).as_posix())
def test_every_relative_link_lands(path: Path) -> None:
    """On a file that exists, and with a fragment on one of its headings."""
    broken = []
    for target in _relative_targets(path):
        file, _, fragment = target.partition("#")
        landing = (path.parent / file).resolve() if file else path
        if not landing.exists():
            broken.append(target)
        elif fragment and fragment not in _anchors(landing.read_text(encoding="utf-8")):
            broken.append(target)

    assert broken == [], f"links that land nowhere: {broken}"


def test_the_overview_lists_every_part() -> None:
    concept = (DOCS / "CONCEPT.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"^\| \[[^\]]+\]\((concept/[a-z-]+\.md)\)", concept, re.M))
    parts = {p.relative_to(DOCS).as_posix() for p in (DOCS / "concept").glob("*.md")}

    assert parts, "docs/concept/ holds no part, so this checked nothing"
    assert listed == parts


@pytest.mark.parametrize(
    "path", sorted((DOCS / "concept").glob("*.md")), ids=lambda p: p.name
)
def test_a_part_names_its_document_and_leads_back(path: Path) -> None:
    first, blank, back = path.read_text(encoding="utf-8").split("\n")[:3]

    assert first.startswith("# Concept: ")
    assert blank == ""
    assert back.startswith("Part of the [concept](../CONCEPT.md)")


def test_a_document_beside_the_overview_is_named_in_capitals() -> None:
    names = [p.name for p in DOCS.glob("*.md")]

    assert names, "docs/ holds no document, so this checked nothing"
    assert [n for n in names if n != n.upper().replace(".MD", ".md")] == []


def test_every_numbered_section_appears_once() -> None:
    """A section moved into two files, or lost on the way, shows here."""
    numbers: list[str] = []
    for path in DOCS.rglob("*.md"):
        numbers += re.findall(
            r"^#{2,6} (\d+(?:\.\d+)?)\.? ", path.read_text(encoding="utf-8"), re.M
        )
    # Three documents carry their section number in the line under the
    # title rather than in a heading.
    for path in DOCS.glob("*.md"):
        found = re.search(
            r"^Section (\d+(?:\.\d+)?) of the \[concept\]",
            path.read_text(encoding="utf-8"),
            re.M,
        )
        if found:
            numbers.append(found.group(1))

    assert len(numbers) == len(set(numbers)), sorted(numbers)
    assert {"1", "4", "7.1", "9.2", "11.2", "14.3", "16", "16.1"} <= set(numbers)
