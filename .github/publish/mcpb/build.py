"""Stage the Claude Desktop bundles (.mcpb) from the checkout.

There are two. The pinned bundle is a uv one: it carries the project's
pyproject.toml, uv.lock and source, and Claude Desktop installs Python and
the dependencies itself on first start. The auto-update bundle carries no
code: it has Claude Desktop run ``uv tool run benethos-lexware-office-mcp``,
which starts the newest release on PyPI, so a new release arrives with a
restart of Claude Desktop, without a new bundle. Staging only copies, so it
needs nothing beyond the standard library and runs the same in CI and
locally:

    python .github/publish/mcpb/build.py <staging dir>
    python .github/publish/mcpb/build.py --auto-update <staging dir>
    npx @anthropic-ai/mcpb@<version> pack <staging dir> <file>.mcpb

The manifest's tools and prompts repeat what the server registers, and one
command writes them from it, in the project's environment since it imports
the package:

    uv run python .github/publish/mcpb/build.py --sync-manifest

The source is what git tracks and nothing else, so a stray file in src/
never ships, and neither a .env nor a config/ directory can: the server
would read either before the per-user files that the configuration
interface writes. The pinned manifest is committed as it ships, its tools
and prompts written by --sync-manifest, everything else by hand. The
auto-update one is made from it here, so its version, tools and fields
cannot drift from it. Of the prompts it declares the setup prompt alone and
says the server lists the rest. tests/test_mcpb.py holds both to the
package.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent

# Destination in the bundle -> source in the checkout.
FILES = {
    "manifest.json": HERE / "manifest.json",
    "server.py": HERE / "server.py",
    "icon.png": REPO / "assets" / "brand" / "icon.png",
    "pyproject.toml": REPO / "pyproject.toml",
    "uv.lock": REPO / "uv.lock",
    # pyproject.toml names it as the readme, and the build fails without it.
    "README.md": REPO / "README.md",
    "LICENSE": REPO / "LICENSE",
}

# The auto-update bundle: what it changes in the pinned manifest. Its own
# name keeps it apart from the pinned bundle in Claude Desktop, which would
# otherwise replace one with the other. The version stays the release's, the
# organisation's action holds it to the tag, and it only says which release
# built the bundle, not which one runs.
AUTO_UPDATE = {
    "name": "benethos-lexware-office-mcp-auto-update",
    "display_name": "Unofficial Lexware Office MCP Server (auto-update)",
    "description": (
        "Unofficial MCP server for the Lexware Office accounting API. Starts "
        "the newest release from PyPI, so a new release arrives with a restart "
        "of Claude Desktop."
    ),
    "server": {
        "type": "uv",
        "entry_point": "benethos-lexware-office-mcp",
        "mcp_config": {
            "command": "uv",
            "args": [
                "tool",
                "run",
                "benethos-lexware-office-mcp",
                "--env-file=${user_config.env_file}",
                "--tools-file=${user_config.tools_file}",
            ],
        },
    },
}

# The one prompt the auto-update bundle declares. It keeps the manifest it
# was installed with while the server moves on, and Claude Desktop holds a
# prompt's answer against the declared text, so a recipe declared there
# would be refused as soon as a release changed a word of it. The recipes
# are left out and `prompts_generated` says the server lists its prompts
# itself, which makes Claude Desktop check no prompt at all, measured
# 2026-11-11. The setup prompt stays declared: its text never changes, the
# installation dialog shows it, and it is the way into the configuration
# for an installation that has no key yet.
# The name is `transport/setup_prompt.SETUP_PROMPT`, written out because
# staging imports nothing of the package.
AUTO_UPDATE_PROMPTS = ("open_setup",)

# Destination in the auto-update bundle -> source. No pyproject.toml, so
# Claude Desktop has no project to install, only the command to run.
AUTO_UPDATE_FILES = {
    "icon.png": FILES["icon.png"],
    "LICENSE": FILES["LICENSE"],
}


def first_sentence(text: str) -> str:
    """A tool description cut to its first sentence, as the manifest lists it.

    Claude Desktop shows these lines before installing, so one sentence each.
    An abbreviation like "e.g." does not end the sentence, and code quotes
    lose their backticks, which the dialog shows as they are.
    """
    line = " ".join(text.split()).replace("`", "")
    head = re.split(r"(?<!e\.g)(?<!i\.e)\. ", line)[0]
    return head.rstrip(".") + "."


def declared_tools() -> list[dict[str, str]]:
    """Every tool the package registers, in order, as the manifest lists it.

    Every tool, not the ones a policy enables: the dialog shows what the
    extension can offer.
    """
    import asyncio

    from benethos_lexware_office_mcp.server import _registry

    return [
        {"name": tool.name, "description": first_sentence(tool.description or "")}
        for tool in asyncio.run(_registry.list_tools())
    ]


def declared_prompts() -> list[dict[str, Any]]:
    """Every prompt, in the order a client lists it, with the text it answers.

    Claude Desktop refuses a prompt the manifest does not declare and drops
    an answer that differs from the declared text. An argument is declared by
    its name and written into the text as Desktop fills it in, so each recipe
    is rendered with that placeholder. The setup prompt answers one fixed
    text, and is not rendered, since that would start the interface.
    """
    import asyncio

    from benethos_lexware_office_mcp.server import build_server
    from benethos_lexware_office_mcp.settings import Settings
    from benethos_lexware_office_mcp.transport.setup_prompt import (
        SETUP_PROMPT,
        SETUP_PROMPT_TEXT,
        offer_setup,
    )

    server = build_server(Settings(tool_policy_path=HERE / "no-tools.json"))
    offer_setup(server, port=0, env_file=None, tools_file=None)
    declared: list[dict[str, Any]] = []
    for prompt in asyncio.run(server.list_prompts()):
        names = [argument.name for argument in prompt.arguments or []]
        entry: dict[str, Any] = {
            "name": prompt.name,
            "description": prompt.description,
        }
        if names:
            entry["arguments"] = names
        if prompt.name == SETUP_PROMPT:
            entry["text"] = SETUP_PROMPT_TEXT
        else:
            placeholders = {name: f"${{arguments.{name}}}" for name in names}
            result = asyncio.run(server.get_prompt(prompt.name, placeholders))
            [message] = result.messages
            entry["text"] = message.content.text
        declared.append(entry)
    return declared


def sync_manifest(path: Path = FILES["manifest.json"]) -> bool:
    """Write the tools and prompts into the manifest. True when it changed.

    Every other field stays as it is written, in its place.
    """
    before = path.read_text(encoding="utf-8")
    manifest: dict[str, Any] = json.loads(before)
    manifest["tools"] = declared_tools()
    manifest["prompts"] = declared_prompts()
    after = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if after == before:
        return False
    path.write_text(after, encoding="utf-8", newline="\n")
    return True


def tracked_source() -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z", "src"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [name for name in listed.split("\0") if name]


def _copy(files: dict[str, Path], target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name, source in files.items():
        shutil.copy2(source, target / name)


def stage(target: Path) -> None:
    _copy(FILES, target)
    for name in tracked_source():
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / name, destination)


def auto_update_manifest() -> dict[str, object]:
    """The pinned manifest with the fields of ``AUTO_UPDATE`` in its place.

    And its prompts cut to ``AUTO_UPDATE_PROMPTS``, with ``prompts_generated``
    right after them.
    """
    pinned: dict[str, Any] = json.loads(
        FILES["manifest.json"].read_text(encoding="utf-8")
    )
    pinned.update(AUTO_UPDATE)
    manifest: dict[str, object] = {}
    for key, value in pinned.items():
        if key == "prompts":
            manifest[key] = [p for p in value if p["name"] in AUTO_UPDATE_PROMPTS]
            manifest["prompts_generated"] = True
        else:
            manifest[key] = value
    return manifest


def stage_auto_update(target: Path) -> None:
    _copy(AUTO_UPDATE_FILES, target)
    (target / "manifest.json").write_text(
        json.dumps(auto_update_manifest(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if arguments == ["--sync-manifest"]:
        changed = sync_manifest()
        state = "updated" if changed else "already in step"
        print(f"manifest.json: tools and prompts {state}", file=sys.stderr)
        sys.exit(0)
    auto_update = arguments[:1] == ["--auto-update"]
    if auto_update:
        arguments = arguments[1:]
    if len(arguments) != 1:
        sys.exit(
            "usage: build.py [--auto-update] <staging dir>\n"
            "       build.py --sync-manifest"
        )
    (stage_auto_update if auto_update else stage)(Path(arguments[0]))
    kind = "auto-update bundle" if auto_update else "bundle"
    print(f"staged the {kind} in {arguments[0]}", file=sys.stderr)
