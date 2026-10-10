"""Stage the Claude Desktop bundle (.mcpb) from the checkout.

The bundle is a uv one: it carries the project's pyproject.toml, uv.lock and
source, and Claude Desktop installs Python and the dependencies itself on
first start. This script only copies, so it needs nothing beyond the
standard library and runs the same in CI and locally:

    python .github/publish/mcpb/build.py <staging dir>
    npx @anthropic-ai/mcpb@<version> pack <staging dir> <file>.mcpb

The source is what git tracks and nothing else, so a stray file in src/
never ships, and neither a .env nor a config/ directory can: the server
would read either before the per-user files that the configuration
interface writes. The manifest is committed as it ships, and
tests/test_mcpb.py holds it to the package.
"""

from __future__ import annotations

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
    "icon.png": REPO / "assets" / "icon.png",
    "pyproject.toml": REPO / "pyproject.toml",
    "uv.lock": REPO / "uv.lock",
    # pyproject.toml names it as the readme, and the build fails without it.
    "README.md": REPO / "README.md",
    "LICENSE": REPO / "LICENSE",
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


def stage(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name, source in FILES.items():
        shutil.copy2(source, target / name)
    for name in tracked_source():
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / name, destination)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: build.py <staging dir>")
    stage(Path(sys.argv[1]))
    print(f"staged the bundle in {sys.argv[1]}", file=sys.stderr)
