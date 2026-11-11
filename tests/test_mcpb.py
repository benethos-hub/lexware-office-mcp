"""The Claude Desktop bundles, kept in step with the package.

The pinned manifest is committed as it ships, so nothing regenerates it on a
release. Its version, tools, prompt and metadata repeat what the package
already says, and each of them is held to that here. The auto-update manifest
is made from it. The bundles are staged by .github/publish/mcpb/build.py,
which runs into a temporary directory below to check what a user's Claude
Desktop would unpack.
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
from benethos_lexware_office_mcp.errors import SETUP_PROMPT_TITLE
from benethos_lexware_office_mcp.server import _registry, build_server
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

# What a failing comparison says to do about it.
SYNC = "run: uv run python .github/publish/mcpb/build.py --sync-manifest"


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
    `build.py --sync-manifest` writes it.
    """
    expected = [
        {"name": tool.name, "description": _first_sentence(tool.description or "")}
        for tool in asyncio.run(_registry.list_tools())
    ]

    assert MANIFEST["tools"] == expected, SYNC


def test_the_prompts_are_declared_as_the_server_answers_them(
    tmp_path: Path,
) -> None:
    """Claude Desktop rejects a prompt it was not told of, or another text.

    Both were measured: an undeclared prompt is refused outright, and an
    answer that differs from the declared text is dropped as a possible
    injection, with "Failed to attach prompt" in the window. An argument is
    declared by its name and written into the text as Desktop fills it in,
    so the server renders each with that placeholder. The setup prompt is
    stubbed, since rendering it would start the interface. Rendered here
    rather than taken from `build.py`, so the command is checked too, and
    `build.py --sync-manifest` writes the list.
    """
    server = build_server(Settings(tool_policy_path=tmp_path / "tools.json"))
    offer_setup(
        server,
        port=8771,
        env_file=None,
        tools_file=None,
        listening=lambda port: True,
        start=lambda command: None,
    )
    expected: list[dict[str, Any]] = []
    for prompt in asyncio.run(server.list_prompts()):
        names = [a.name for a in prompt.arguments or []]
        placeholders = {name: f"${{arguments.{name}}}" for name in names}
        result = asyncio.run(server.get_prompt(prompt.name, placeholders))
        [message] = result.messages
        entry: dict[str, Any] = {
            "name": prompt.name,
            "description": prompt.description,
        }
        if names:
            entry["arguments"] = names
        entry["text"] = message.content.text
        expected.append(entry)

    assert expected[-1]["text"] == SETUP_PROMPT_TEXT
    assert MANIFEST["prompts"] == expected, SYNC


def test_the_sync_writes_tools_and_prompts_and_nothing_else(tmp_path: Path) -> None:
    """A stale copy comes back as the committed file, byte for byte.

    The committed one is in step already, so the command leaves it alone, and
    a field it does not own keeps its value and its place.
    """
    build = _build_script()
    stale = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    stale["tools"] = stale["tools"][:1]
    stale["prompts"] = []
    copy = tmp_path / "manifest.json"
    copy.write_text(json.dumps(stale, indent=2), encoding="utf-8")

    assert build.sync_manifest(copy) is True
    assert copy.read_bytes() == (BUNDLE / "manifest.json").read_bytes()
    assert build.sync_manifest(copy) is False


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
    assert server["entry_point"] == "server.py" and args[4] == "server.py"
    assert args[5:] == [
        "--env-file=${user_config.env_file}",
        "--tools-file=${user_config.tools_file}",
    ]


def test_the_bundle_asks_for_the_two_files_and_nothing_else() -> None:
    """Every setting is made in the configuration interface the prompt opens.

    A key asked for here would reach the server as an environment variable,
    which beats the .env and so could no longer be changed on those pages, so
    the only fields are the paths of the two files.

    The = form with an empty default is what Claude Desktop substitutes when
    a field is empty. The plain form, a placeholder as its own argument,
    passes the placeholder through (measured 2026-11-05, Desktop 4.16336).
    """
    fields = MANIFEST["user_config"]
    config = MANIFEST["server"]["mcp_config"]

    assert set(fields) == {"env_file", "tools_file"}
    for field in fields.values():
        assert field["type"] == "file"
        assert field["required"] is False
        assert field["default"] == ""
        assert not field.get("multiple", False)
        assert not field.get("sensitive", False)
    assert "env" not in config
    assert all(not re.fullmatch(r"\$\{user_config\.\w+\}", a) for a in config["args"])


def test_the_data_goes_where_a_privacy_policy_says() -> None:
    """Claude Desktop wants one as soon as data leaves for another service."""
    assert MANIFEST["privacy_policies"] == ["https://datenschutz.lexware.de/"]


# -- what ends up in the bundle -----------------------------------------------


def _script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"mcpb_{name}", BUNDLE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_script() -> ModuleType:
    return _script("build")


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
        REPO / "assets" / "brand" / "icon.png"
    ).read_bytes()


def test_the_icon_is_the_size_claude_desktop_recommends() -> None:
    png = (REPO / "assets" / "brand" / "icon.png").read_bytes()

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert (int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")) == (
        512,
        512,
    )


# -- the auto-update bundle -----------------------------------------------------


def test_the_auto_update_manifest_is_the_pinned_one_in_all_but_its_own_fields() -> None:
    """Version, tools and fields come from the pinned one, so they stay."""
    build = _build_script()
    manifest = build.auto_update_manifest()
    own = set(build.AUTO_UPDATE) | {"prompts", "prompts_generated"}

    assert set(build.AUTO_UPDATE) == {"name", "display_name", "description", "server"}
    assert {k: v for k, v in manifest.items() if k not in own} == {
        k: v for k, v in MANIFEST.items() if k not in own
    }
    assert manifest["version"] == benethos_lexware_office_mcp.__version__
    # It opens as the project's does, so a new description in pyproject.toml
    # cannot leave this card behind.
    assert manifest["description"].startswith(MANIFEST["description"].split(" — ")[0])


def test_the_auto_update_bundle_declares_the_setup_prompt_alone() -> None:
    """It keeps its manifest while the server moves on, so a declared recipe
    would be refused once a release changed its text. The setup prompt stays,
    with the text the pinned manifest declares, and the server lists the
    rest. The pinned bundle declares every prompt and generates none."""
    build = _build_script()
    manifest = build.auto_update_manifest()
    keys = list(manifest)

    assert build.AUTO_UPDATE_PROMPTS == (SETUP_PROMPT,)
    assert manifest["prompts"] == [
        p for p in MANIFEST["prompts"] if p["name"] == SETUP_PROMPT
    ]
    assert manifest["prompts_generated"] is True
    assert keys.index("prompts_generated") == keys.index("prompts") + 1
    assert "prompts_generated" not in MANIFEST
    assert len(MANIFEST["prompts"]) > 1


def test_the_auto_update_bundle_stands_beside_the_pinned_one() -> None:
    """Claude Desktop keys an extension by its name, the same one would replace it."""
    manifest = _build_script().auto_update_manifest()

    assert manifest["name"] == PROJECT["name"] + "-auto-update"
    assert manifest["display_name"] == MANIFEST["display_name"] + " (auto-update)"


def test_the_auto_update_bundle_runs_the_newest_release_from_the_index() -> None:
    """No version, no lockfile, no directory: uv resolves the newest release.

    The two files are passed exactly as the pinned bundle passes them, the same
    form for the same reason, so the extension's page means the same in both.
    """
    server = _build_script().auto_update_manifest()["server"]
    pinned = MANIFEST["server"]["mcp_config"]["args"]

    assert server["type"] == "uv"
    assert server["entry_point"] == PROJECT["name"]
    assert server["mcp_config"]["command"] == "uv"
    assert server["mcp_config"]["args"] == ["tool", "run", PROJECT["name"], *pinned[5:]]
    assert "env" not in server["mcp_config"]


def test_the_staged_auto_update_bundle_carries_no_project(tmp_path: Path) -> None:
    """Without a pyproject.toml Claude Desktop has nothing to install."""
    build = _build_script()
    target = tmp_path / "auto-update"

    build.stage_auto_update(target)

    assert sorted(p.name for p in target.iterdir()) == [
        "LICENSE",
        "icon.png",
        "manifest.json",
    ]
    staged = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert staged == build.auto_update_manifest()
    assert (target / staged["icon"]).read_bytes() == (
        REPO / "assets" / "brand" / "icon.png"
    ).read_bytes()


def test_the_prompt_stays_what_installed_extensions_declare() -> None:
    """An extension that updates itself keeps the manifest it was installed with.

    It runs the newest server against the prompt declared by an older release.
    Claude Desktop refuses an undeclared prompt and drops an answer that differs
    from the declared text, so a new name or a new word here would break the
    setup on every one of them, with no new file to reach them through. Changing
    this takes a new way into the setup, not a new expected value.
    """
    assert SETUP_PROMPT == "open_setup"
    assert SETUP_PROMPT_TEXT == (
        "The configuration interface of the Lexware Office MCP server is open in "
        "the browser, where the person sets the API key and which tools exist. "
        "Nothing needs to be done in this conversation."
    )


# -- the release job ------------------------------------------------------------


def test_the_job_stages_here_and_lets_the_organisation_pack_and_attach() -> None:
    """Staging is this project's, packing, checking and attaching the action's.

    The name without a version is the README's link to the newest release.
    """
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    job = workflow.split("\n  mcpb-bundle:\n", 1)[1].split("\n  mcp-registry:\n")[0]
    head, steps = job.split("steps:", 1)

    assert "if: github.event_name == 'release'" in head
    assert "      contents: write" in head
    assert "persist-credentials: false" in steps
    staging = (
        'run: uv run --no-project .github/publish/mcpb/build.py "$RUNNER_TEMP/bundle"'
    )
    action = "uses: benethos-hub/.github/actions/publish/mcpb@main"
    assert steps.index(staging) < steps.index(action)
    assert "staged: ${{ runner.temp }}/bundle\n" in steps
    assert "name: benethos-lexware-office-mcp\n" in steps


def test_both_bundles_are_staged_and_attached_under_their_names() -> None:
    """Each through the action, so each comes with and without its version."""
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    job = workflow.split("\n  mcpb-bundle:\n", 1)[1].split("\n  mcp-registry:\n")[0]

    assert (
        "run: uv run --no-project .github/publish/mcpb/build.py --auto-update "
        '"$RUNNER_TEMP/bundle-auto-update"' in job
    )
    assert "staged: ${{ runner.temp }}/bundle-auto-update\n" in job
    assert re.findall(r"^\s+name: (benethos-[a-z-]+)$", job, re.M) == [
        "benethos-lexware-office-mcp",
        "benethos-lexware-office-mcp-auto-update",
    ]
    assert job.count("uses: benethos-hub/.github/actions/publish/mcpb@main") == 2
