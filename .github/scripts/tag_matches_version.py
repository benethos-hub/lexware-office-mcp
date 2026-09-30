"""Fail a release whose tag is not the package version.

The tag and the version are written in two places. A tag v0.4.0 on a commit
whose pyproject.toml still says 0.3.0 would make PyPI refuse the upload,
while the image job went on to push 0.4.0, 0.4 and latest with the old code.
Run by both publish jobs before anything is built. GITHUB_REF_NAME holds the
tag on a release.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path


def main() -> int:
    tag = os.environ.get("GITHUB_REF_NAME", "")
    pyproject = Path(os.environ.get("PYPROJECT", "pyproject.toml"))
    version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    if tag.removeprefix("v") != version:
        print(
            f"::error::Release tag {tag!r} is not the package version {version!r} "
            f"in {pyproject}. Bump the version first, or tag v{version}."
        )
        return 1
    print(f"Release tag {tag} matches the package version {version}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
