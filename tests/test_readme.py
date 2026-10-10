"""What the README promises, checked against the code and against PyPI.

The README ships verbatim as the package description. PyPI renders that text
on its own, without the repository around it, so a relative target like
``[LICENSE](LICENSE)`` becomes ``pypi.org/project/<name>/LICENSE`` and leads
nowhere. It looks right on GitHub, which is why the mistake survives review,
and it cannot be repaired afterwards: PyPI re-renders the description only
when a new distribution is uploaded.

Fragment links are fine. PyPI rewrites them to ``#user-content-<anchor>``.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from benethos_lexware_office_mcp.server import build_server
from benethos_lexware_office_mcp.settings import Settings

README = Path(__file__).resolve().parents[1] / "README.md"

# Only the `](target)` tail, never the label before it. A badge is a link
# wrapped around an image, `[![alt](img)](target)`, and a pattern that tries to
# balance the brackets misses the outer target of exactly that construct.
_LINK = re.compile(r"\]\(([^)\s]+)\)")

# An HTML image, like the icon in the title, carries its target in `src`.
_SRC = re.compile(r"""<img\b[^>]*?\bsrc=["']([^"']+)["']""")

# Fenced blocks hold example commands and paths, which are not page links.
_FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


def _link_targets(markdown: str) -> list[str]:
    text = _FENCE.sub("", markdown)
    return _LINK.findall(text) + _SRC.findall(text)


def test_readme_has_no_relative_links() -> None:
    """Every target has to survive being rendered outside the repository."""
    offenders = [
        target
        for target in _link_targets(README.read_text(encoding="utf-8"))
        if not target.startswith(("http://", "https://", "#", "mailto:"))
    ]

    assert not offenders, (
        "Relative targets break on PyPI, which renders the README without the "
        f"repository around it. Use an absolute URL for: {offenders}"
    )


def test_the_link_check_would_catch_a_relative_target() -> None:
    """A guard is worth having only if it fires."""
    sample = "See [LICENSE](LICENSE) and [docs](https://example.com).\n"

    assert _link_targets(sample) == ["LICENSE", "https://example.com"]


def test_the_link_check_sees_through_a_badge() -> None:
    """The outer target is the one that has to be checked."""
    sample = "[![License](https://img.shields.io/badge/x)](LICENSE)\n"

    assert _link_targets(sample) == ["https://img.shields.io/badge/x", "LICENSE"]


def test_the_link_check_sees_an_html_image() -> None:
    """An `<img>` is no Markdown link, and its source breaks the same way."""
    sample = '# <img src="assets/icon.svg" alt="" width="40"> Title\n'

    assert _link_targets(sample) == ["assets/icon.svg"]


def test_the_link_check_ignores_code_blocks() -> None:
    """A path inside a fence is an example, not a link."""
    sample = "Text [ok](https://example.com)\n\n```\ncp [a](b) elsewhere\n```\n"

    assert _link_targets(sample) == ["https://example.com"]


# The table of contents and the cross-references jump to headings by their
# anchor, which GitHub derives from the heading text. Rename a heading and the
# link still renders, it just lands nowhere, on GitHub and on PyPI alike.
_HEADING = re.compile(r"^(#{1,6}) (.+)$", re.MULTILINE)


def _anchor(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces
    to hyphens. HTML in the heading, like the icon in the title, is not text."""
    text = re.sub(r"<[^>]+>", "", heading).strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def _anchors(markdown: str) -> set[str]:
    anchors: set[str] = set()
    for _, heading in _HEADING.findall(_FENCE.sub("", markdown)):
        anchor = _anchor(heading)
        # A repeated heading gets -1, -2 and so on.
        suffix, unique = 0, anchor
        while unique in anchors:
            suffix += 1
            unique = f"{anchor}-{suffix}"
        anchors.add(unique)
    return anchors


def test_every_fragment_link_lands_on_a_heading() -> None:
    text = README.read_text(encoding="utf-8")
    fragments = {t[1:] for t in _link_targets(text) if t.startswith("#")}

    assert fragments, "the README has no fragment links, so this checked nothing"
    missing = sorted(fragments - _anchors(text))
    assert not missing, (
        f"links to {missing} land on no heading. A heading was renamed or the "
        "link was mistyped."
    )


def test_the_contents_name_every_section() -> None:
    """A section added below and not to the contents is one nobody finds."""
    text = README.read_text(encoding="utf-8")
    contents = text.split("**Contents**", 1)[1].split("\n\n", 2)[1]
    listed = set(re.findall(r"\]\(#([^)]+)\)", contents))
    sections = {
        _anchor(heading)
        for level, heading in _HEADING.findall(_FENCE.sub("", text))
        if level == "##"
    }

    assert sorted(sections - listed) == []


def test_anchor_follows_githubs_rules() -> None:
    assert _anchor("Where a value comes from, and which one wins") == (
        "where-a-value-comes-from-and-which-one-wins"
    )
    assert _anchor("Switching individual tools off") == (
        "switching-individual-tools-off"
    )
    assert _anchor('<img src="x.svg" alt=""> Title') == "title"
    assert _anchors("## Logs\n\n## Logs\n") == {"logs", "logs-1"}


def _documented_tools(markdown: str) -> set[str]:
    """The tool names in the tables under `## Tools`, and nowhere else.

    Scoped to that section on purpose: the rest of the README says
    `create_contact` in prose and names presets like `read-only`, and neither
    is a claim about what the server offers.
    """
    start = markdown.index("## Tools")
    end = markdown.index("## ", start + len("## Tools"))
    return set(re.findall(r"^\| `([a-z_]+)`", markdown[start:end], re.M))


def test_the_readme_lists_exactly_the_tools_that_exist() -> None:
    """Adding a tool and forgetting its row is the realistic mistake.

    The tool works, every test passes, and the only symptom is that nobody
    reading the documentation knows it is there. The reverse sends a reader
    after something that was renamed or removed.
    """
    # conftest.py's policy file has every tool on.
    server = build_server(Settings())
    registered = {tool.name for tool in asyncio.run(server.list_tools())}
    documented = _documented_tools(README.read_text(encoding="utf-8"))

    missing = sorted(registered - documented)
    assert not missing, (
        f"registered but absent from the README: {missing}. A tool nobody can "
        "read about is a tool nobody enables."
    )

    phantom = sorted(documented - registered)
    assert not phantom, (
        f"in the README but not registered: {phantom}. A reader will go "
        "looking for something that is not there."
    )


def test_the_tool_table_scope_is_the_tools_section_only() -> None:
    """The scoping is the part of this that can quietly stop working."""
    sample = "## Tools\n\n| `get_thing` | does |\n\n## Later\n\n| `not_a_tool` | x |\n"

    assert _documented_tools(sample) == {"get_thing"}


@pytest.mark.parametrize("preset", ["read-only", "write", "irreversible"])
def test_the_readme_names_the_presets_that_exist(preset: str) -> None:
    """A preset the README invents is an instruction that fails when followed."""
    assert f"`{preset}`" in README.read_text(encoding="utf-8") or (
        f"--tools {preset}" in README.read_text(encoding="utf-8")
    )
