"""The Claude Desktop bundle, kept in step with the package.

The manifest is committed as it ships, so nothing regenerates it on a
release. Its version, tools, prompt and metadata repeat what the package
already says, and each of them is held to that here. The bundle itself is
staged by .github/publish/mcpb/build.py, which runs into a temporary
directory below to check what a user's Claude Desktop would unpack.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import subprocess
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import benethos_lexware_office_mcp
from benethos_lexware_office_mcp.server import (
    SETUP_PROMPT_TITLE,
    _registry,
    build_server,
)
from benethos_lexware_office_mcp.settings import Settings
from benethos_lexware_office_mcp.transport.setup_prompt import (
    SETUP_PROMPT,
    SETUP_PROMPT_TEXT,
    offer_setup,
)

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / ".github" / "publish" / "mcpb"
MANIFEST: dict[str, Any] = json.loads(
    (BUNDLE / "manifest.json").read_text(encoding="utf-8")
)
PROJECT: dict[str, Any] = tomllib.loads(
    (REPO / "pyproject.toml").read_text(encoding="utf-8")
)["project"]


def _first_sentence(text: str) -> str:
    """A tool description cut to its first sentence, as the manifest lists it.

    Claude Desktop shows these lines before installing, so one sentence each.
    An abbreviation like "e.g." does not end the sentence, and code quotes
    lose their backticks, which the dialog shows as they are.
    """
    line = " ".join(text.split()).replace("`", "")
    head = re.split(r"(?<!e\.g)(?<!i\.e)\. ", line)[0]
    return head.rstrip(".") + "."


# -- what the manifest repeats from the package ------------------------------


def test_the_version_is_the_package_version() -> None:
    assert MANIFEST["version"] == benethos_lexware_office_mcp.__version__


def test_the_metadata_is_the_packages() -> None:
    assert MANIFEST["name"] == PROJECT["name"]
    assert MANIFEST["description"] == PROJECT["description"]
    assert MANIFEST["author"]["name"] == PROJECT["authors"][0]["name"]
    assert MANIFEST["license"] == PROJECT["license"]["text"]
    assert MANIFEST["keywords"] == PROJECT["keywords"]
    assert (
        MANIFEST["compatibility"]["runtimes"]["python"] == (PROJECT["requires-python"])
    )


def test_the_tools_are_every_registered_one() -> None:
    """Same tools, same order, each with the first sentence of its description.

    Every tool, not the ones a policy enables: the dialog shows what the
    extension can offer, and the long description says that none is on until
    the person chooses. A changed docstring changes the line here too, and
    the expected list is printed so it can be pasted into the manifest.
    """
    expected = [
        {"name": tool.name, "description": _first_sentence(tool.description or "")}
        for tool in asyncio.run(_registry.list_tools())
    ]

    assert MANIFEST["tools"] == expected, json.dumps(expected, indent=2)


def test_the_prompt_is_declared_as_the_server_answers_it(tmp_path: Path) -> None:
    """Claude Desktop rejects a prompt it was not told of, or another text.

    Both were measured: an undeclared prompt is refused outright, and an
    answer that differs from the declared text is dropped as a possible
    injection, with "Failed to attach prompt" in the window.
    """
    server = build_server(Settings(tool_policy_path=tmp_path / "tools.json"))
    offer_setup(server, port=8771, env_file=None, tools_file=None)
    [prompt] = asyncio.run(server.list_prompts())

    assert MANIFEST["prompts"] == [
        {
            "name": SETUP_PROMPT,
            "description": prompt.description,
            "text": SETUP_PROMPT_TEXT,
        }
    ]


def test_the_description_says_how_to_begin() -> None:
    """Claude Desktop calls a server with no tools failed, until one is on."""
    assert f"**{SETUP_PROMPT_TITLE}**" in MANIFEST["long_description"]
    assert "Nothing is enabled" in MANIFEST["long_description"]


# -- how Claude Desktop starts it ---------------------------------------------


def test_it_is_a_uv_bundle_started_from_its_own_directory() -> None:
    server = MANIFEST["server"]

    assert MANIFEST["manifest_version"] == "0.4"
    assert server["type"] == "uv"
    assert server["mcp_config"]["command"] == "uv"
    args = server["mcp_config"]["args"]
    assert args[:3] == ["run", "--directory", "${__dirname}"]
    # The lockfile decides the versions, as it does for the image.
    assert "--frozen" in args
    assert args[-1] == server["entry_point"] == "server.py"


def test_the_bundle_asks_for_no_settings() -> None:
    """Everything is set in the configuration interface the prompt opens.

    A key asked for here would reach the server as an environment variable,
    which beats the .env and so could no longer be changed on those pages.
    """
    assert "user_config" not in MANIFEST
    assert "env" not in MANIFEST["server"]["mcp_config"]


def test_the_data_goes_where_a_privacy_policy_says() -> None:
    """Claude Desktop wants one as soon as data leaves for another service."""
    assert MANIFEST["privacy_policies"] == ["https://datenschutz.lexware.de/"]


# -- what ends up in the bundle -----------------------------------------------


def _build_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mcpb_build", BUNDLE / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_staged_bundle_holds_what_uv_needs_and_no_more(tmp_path: Path) -> None:
    """The source as git tracks it, so no stray file, no .env, no config/."""
    target = tmp_path / "bundle"

    _build_script().stage(target)

    assert sorted(p.name for p in target.iterdir()) == [
        "LICENSE",
        "README.md",
        "icon.png",
        "manifest.json",
        "pyproject.toml",
        "server.py",
        "src",
        "uv.lock",
    ]
    tracked = subprocess.run(
        ["git", "ls-files", "src"], cwd=REPO, capture_output=True, text=True
    ).stdout.split()
    staged = sorted(
        p.relative_to(target).as_posix()
        for p in (target / "src").rglob("*")
        if p.is_file()
    )
    assert staged == sorted(tracked)
    assert not list(target.rglob("__pycache__"))
    assert (target / MANIFEST["icon"]).read_bytes() == (
        REPO / "assets" / "icon.png"
    ).read_bytes()


def test_the_icon_is_the_size_claude_desktop_recommends() -> None:
    png = (REPO / "assets" / "icon.png").read_bytes()

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert (int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")) == (
        512,
        512,
    )


# -- the release job ------------------------------------------------------------


def test_the_job_checks_the_tag_and_attaches_both_names() -> None:
    """The name without a version is the README's link to the newest release."""
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    job = workflow.split("  mcpb-bundle:", 1)[1].split("\n  mcp-registry-publish:")[0]
    head, steps = job.split("steps:", 1)

    assert "if: github.event_name == 'release'" in head
    assert "      contents: write" in head
    assert re.search(r"MCPB_VERSION: \d+\.\d+\.\d+\n", head)
    assert "persist-credentials: false" in steps
    assert steps.index("tag_matches_version.py") < steps.index("build.py")
    assert 'gh release upload "$GITHUB_REF_NAME" "$versioned" ' in steps
    assert "benethos-lexware-office-mcp.mcpb" in steps
