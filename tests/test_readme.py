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
import json
import re
from pathlib import Path

import pytest

from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.policy import known_tools
from benethos_lexware_office_mcp.server import build_server

README = Path(__file__).resolve().parents[1] / "README.md"

# Only the `](target)` tail, never the label before it. A badge is a link
# wrapped around an image, `[![alt](img)](target)`, and a pattern that tries to
# balance the brackets misses the outer target of exactly that construct.
_LINK = re.compile(r"\]\(([^)\s]+)\)")

# Fenced blocks hold example commands and paths, which are not page links.
_FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


def _link_targets(markdown: str) -> list[str]:
    return _LINK.findall(_FENCE.sub("", markdown))


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


def test_the_link_check_ignores_code_blocks() -> None:
    """A path inside a fence is an example, not a link."""
    sample = "Text [ok](https://example.com)\n\n```\ncp [a](b) elsewhere\n```\n"

    assert _link_targets(sample) == ["https://example.com"]


def test_every_anchor_points_at_a_heading_that_exists() -> None:
    """A fragment link is rewritten by PyPI, not repaired by it."""
    text = README.read_text(encoding="utf-8")
    headings = {
        re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-")
        for h in re.findall(r"^#{2,4} (.+)$", text, re.M)
    }
    dead = [a for a in re.findall(r"\]\(#([a-z0-9-]+)\)", text) if a not in headings]

    assert not dead, f"anchors with no heading behind them: {dead}"


def _documented_tools(markdown: str) -> set[str]:
    """The tool names in the tables under `## Tools`, and nowhere else.

    Scoped to that section on purpose: the rest of the README says
    `create_contact` in prose and names presets like `read-only`, and neither
    is a claim about what the server offers.
    """
    start = markdown.index("## Tools")
    end = markdown.index("## ", start + len("## Tools"))
    return set(re.findall(r"^\| `([a-z_]+)`", markdown[start:end], re.M))


def test_the_readme_lists_exactly_the_tools_that_exist(tmp_path: Path) -> None:
    """Adding a tool and forgetting its row is the realistic mistake.

    The tool works, every test passes, and the only symptom is that nobody
    reading the documentation knows it is there. The reverse sends a reader
    after something that was renamed or removed.
    """
    policy = tmp_path / "tools.json"
    policy.write_text(json.dumps(dict.fromkeys(known_tools(), True)), encoding="utf-8")
    server = build_server(Settings(tool_policy_path=policy))
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
