"""What the package ships, and what the documentation says it is.

Two kinds of thing that break without breaking anything: a file that quietly
stops being packed, and a version quoted as an example that nobody thought to
move at release time.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
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
    # An exact image tag in backticks. The minor line beside it has only two
    # components, so it is not matched here - it is checked below instead.
    ("README.md", r"`:(\d+\.\d+\.\d+)`"),
    ("compose.yaml", r"`:(\d+\.\d+\.\d+)`"),
    # The status line each document opens with.
    ("README.md", r"\*\*Status: (\d+\.\d+\.\d+)"),
    ("SPECS.md", r"\*\*Status: (\d+\.\d+\.\d+)"),
)

# The minor-line tag, which follows patch releases rather than naming one. It
# is right for it to stay put across a patch bump and wrong for it to stay put
# across a minor one, so it is compared against the first two components rather
# than against the whole version. Nothing else here would notice: the tag keeps
# resolving, it simply stops at the previous line and never sees this release.
MINOR_LINE_EXAMPLES = (
    ("README.md", r"`:(\d+\.\d+)`"),
    ("compose.yaml", r"`:(\d+\.\d+)`"),
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


@pytest.mark.parametrize(("relative_path", "pattern"), MINOR_LINE_EXAMPLES)
def test_the_documented_minor_line_examples_are_current(
    relative_path: str, pattern: str
) -> None:
    text = (REPO / relative_path).read_text(encoding="utf-8")
    found = re.findall(pattern, text)

    assert found, f"{relative_path} no longer contains {pattern!r}"

    major, minor, *_ = benethos_lexware_office_mcp.__version__.split(".")
    current = f"{major}.{minor}"
    stale = sorted({v for v in found if v != current})
    assert not stale, (
        f"{relative_path} still offers {stale} as the minor line to follow, but "
        f"the package is on {current}. That tag stops at the previous minor and "
        "never sees this release."
    )


def test_the_version_check_would_notice_a_stale_example() -> None:
    """The guard is worth having only if it fires."""
    pattern = r"benethos-lexware-office-mcp==(\d+\.\d+\.\d+)"
    sample = 'uvx "benethos-lexware-office-mcp==0.0.1"'

    found = re.findall(pattern, sample)

    assert found == ["0.0.1"]
    assert found != [benethos_lexware_office_mcp.__version__]


# -- what Docker keeps of the output ----------------------------------------

COMPOSE = REPO / "compose.yaml"


def _tag_check(tag: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "0.3.0"\n', encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(REPO / ".github" / "scripts" / "tag_matches_version.py")],
        env={**os.environ, "GITHUB_REF_NAME": tag, "PYPROJECT": str(pyproject)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_release_tag_that_is_the_version_passes(tmp_path: Path) -> None:
    assert _tag_check("v0.3.0", tmp_path).returncode == 0


def test_a_release_tag_ahead_of_the_version_fails(tmp_path: Path) -> None:
    """PyPI would refuse it, and the image would go out under it anyway."""
    done = _tag_check("v0.4.0", tmp_path)

    assert done.returncode == 1
    assert "::error::" in done.stdout


def test_both_publish_jobs_check_the_tag() -> None:
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("run: python3 .github/scripts/tag_matches_version.py") == 2


def test_compose_caps_the_log_docker_keeps() -> None:
    """Five files of 10 MB, the json-file driver's own rotation.

    Without it Docker keeps every access line for the life of the container,
    and a restart is the same container. Read as text rather than parsed:
    the check is that the block exists with these values, and a YAML parser
    is not a dependency of this project.
    """
    text = COMPOSE.read_text(encoding="utf-8")

    block = re.search(r"^x-logging: &logging\n((?:  .*\n)+)", text, flags=re.MULTILINE)
    assert block is not None, "the shared logging block is gone"
    assert "driver: json-file" in block.group(1)
    assert 'max-size: "10m"' in block.group(1)
    assert 'max-file: "5"' in block.group(1)


def test_every_compose_service_uses_the_log_cap() -> None:
    """A service added later without the reference would log without limit."""
    text = COMPOSE.read_text(encoding="utf-8")
    services = text.split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    names = re.findall(r"^  ([a-z][\w-]*):\n", services, flags=re.MULTILINE)

    assert names == ["benethos-lexware-office-mcp", "setup"]
    assert services.count("    logging: *logging\n") == len(names)


def test_the_readme_run_example_caps_the_log_as_well() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    assert "--log-opt max-size=10m --log-opt max-file=5" in readme
