"""Stage the Claude Desktop bundles (.mcpb) from the checkout.

There are two. The pinned bundle is a uv one: it carries the project's
pyproject.toml, uv.lock and source, and Claude Desktop installs Python and
the dependencies itself on first start. The auto-update bundle carries no
code: it has Claude Desktop run ``uv tool run benethos-lexware-office-mcp``,
which starts the newest release on PyPI, so a new release arrives with a
restart of Claude Desktop, without a new bundle. This script only copies, so
it needs nothing beyond the standard library and runs the same in CI and
locally:

    python .github/publish/mcpb/build.py <staging dir>
    python .github/publish/mcpb/build.py --auto-update <staging dir>
    npx @anthropic-ai/mcpb@<version> pack <staging dir> <file>.mcpb

The source is what git tracks and nothing else, so a stray file in src/
never ships, and neither a .env nor a config/ directory can: the server
would read either before the per-user files that the configuration
interface writes. The pinned manifest is committed as it ships. The
auto-update one is made from it here, so its version, tools, prompt and
fields cannot drift from it. tests/test_mcpb.py holds both to the package.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

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

# Destination in the auto-update bundle -> source. No pyproject.toml, so
# Claude Desktop has no project to install, only the command to run.
AUTO_UPDATE_FILES = {
    "icon.png": FILES["icon.png"],
    "LICENSE": FILES["LICENSE"],
}


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
    """The pinned manifest with the fields of ``AUTO_UPDATE`` in its place."""
    manifest: dict[str, object] = json.loads(
        FILES["manifest.json"].read_text(encoding="utf-8")
    )
    manifest.update(AUTO_UPDATE)
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
    auto_update = arguments[:1] == ["--auto-update"]
    if auto_update:
        arguments = arguments[1:]
    if len(arguments) != 1:
        sys.exit("usage: build.py [--auto-update] <staging dir>")
    (stage_auto_update if auto_update else stage)(Path(arguments[0]))
    kind = "auto-update bundle" if auto_update else "bundle"
    print(f"staged the {kind} in {arguments[0]}", file=sys.stderr)
