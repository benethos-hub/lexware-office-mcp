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
from benethos_lexware_office_mcp import cli

PACKAGE_DIR = Path(benethos_lexware_office_mcp.__file__).resolve().parent
REPO = PACKAGE_DIR.parents[1]
MARKER = PACKAGE_DIR / "py.typed"
DOCKERFILE = REPO / "containers" / "images" / "lexware-office-mcp" / "Dockerfile"


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


# The documentation quotes the current version in several places, most of them
# an example somebody is meant to copy. The failure mode is forgetting at
# release time, not difficulty, so this asserts rather than rewrites: the
# suite goes red until the examples agree with the package. The lockfile
# carries the version too, and `uv lock --check` in CI watches that one.
VERSION_EXAMPLES = (
    # The exact pin the client configuration shows.
    ("README.md", r"benethos-lexware-office-mcp==(\d+\.\d+\.\d+)"),
    # An exact image tag in backticks. The minor line beside it has only two
    # components, so it is not matched here - it is checked below instead.
    ("README.md", r"`:(\d+\.\d+\.\d+)`"),
    # The version the production folder runs.
    ("containers/production/.env.example", r"(?m)^LXO_VERSION=(\d+\.\d+\.\d+)$"),
    # The status line each document opens with.
    ("README.md", r"\*\*Status: (\d+\.\d+\.\d+)"),
    ("SPECS.md", r"\*\*Status: (\d+\.\d+\.\d+)"),
    # The start line the log catalogue shows as an example.
    ("SPECS.md", r"`(\d+\.\d+\.\d+) started over stdio`"),
)

# The minor-line tag, which follows patch releases rather than naming one. It
# is right for it to stay put across a patch bump and wrong for it to stay put
# across a minor one, so it is compared against the first two components rather
# than against the whole version. Nothing else here would notice: the tag keeps
# resolving, it simply stops at the previous line and never sees this release.
MINOR_LINE_EXAMPLES = (
    ("README.md", r"`:(\d+\.\d+)`"),
    ("containers/production/.env.example", r"`(\d+\.\d+)`"),
    # The release list names it as the one to move with a minor release.
    ("CLAUDE.md", r"`:(\d+\.\d+)`"),
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


def test_the_changelog_has_a_section_for_this_version() -> None:
    """Its heading, its link, and the unreleased link starting after it."""
    version = re.escape(benethos_lexware_office_mcp.__version__)
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    compare = re.escape("https://github.com/benethos-hub/lexware-office-mcp/compare/")

    assert re.search(rf"^## \[{version}\] - \d{{4}}-\d{{2}}-\d{{2}}$", text, re.M)
    assert re.search(rf"^\[{version}\]: {compare}v[\d.]+\.\.\.v{version}$", text, re.M)
    assert re.search(rf"^\[Unreleased\]: {compare}v{version}\.\.\.HEAD$", text, re.M)


def test_the_roadmap_has_a_row_for_this_version() -> None:
    text = (REPO / "SPECS.md").read_text(encoding="utf-8")

    assert f"\n| {benethos_lexware_office_mcp.__version__} | " in text


def test_the_version_check_would_notice_a_stale_example() -> None:
    """The guard is worth having only if it fires."""
    pattern = r"benethos-lexware-office-mcp==(\d+\.\d+\.\d+)"
    sample = 'uvx "benethos-lexware-office-mcp==0.0.1"'

    found = re.findall(pattern, sample)

    assert found == ["0.0.1"]
    assert found != [benethos_lexware_office_mcp.__version__]


# -- what Docker keeps of the output ----------------------------------------

CONTAINERS = REPO / "containers"
# Development first, production second, in every test that tells them apart.
COMPOSE_FILES = (
    CONTAINERS / "development" / "compose.yaml",
    CONTAINERS / "production" / "compose.yaml",
)


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


def test_the_publishing_environment_is_named_for_the_package() -> None:
    """pypi- and the package's name, the one PyPI's publisher is bound to.

    A renamed environment is refused by PyPI at the next release, not before,
    so the name in the header the publisher is set up from and the name the
    job uses have to be the same one.
    """
    import tomllib

    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    environment = f"pypi-{project['project']['name']}"
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )

    assert f"\n      name: {environment}\n" in workflow
    assert f"#     Environment:       {environment}\n" in workflow


def test_the_image_is_pushed_under_the_package_name_first() -> None:
    """The readback inspects the first name, so that has to be the new one.

    The repository's name follows for the 0.4 patch releases, until 0.5.0.
    """
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    block = workflow.split("          images: |\n", 1)[1].split("\n          flavor:")[
        0
    ]
    images = [line.strip() for line in block.splitlines()]

    assert images == [
        "ghcr.io/${{ github.repository_owner }}/benethos-lexware-office-mcp",
        "ghcr.io/${{ github.repository }}",
    ]


def test_both_publish_jobs_check_the_tag() -> None:
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("run: python3 .github/scripts/tag_matches_version.py") == 2


def test_latest_never_follows_a_pre_release() -> None:
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    latest = [line for line in workflow.splitlines() if "value=latest" in line]

    assert latest
    assert all("!github.event.release.prerelease" in line for line in latest)


def test_a_manual_run_pushes_the_image_from_main_only() -> None:
    """`edge` is public, and a manual run can be started on any branch."""
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    job = workflow.split("  ghcr-publish:", 1)[1]

    assert (
        "if: github.event_name == 'release' || github.ref == 'refs/heads/main'"
        in job.split("steps:", 1)[0]
    )


def test_every_action_is_pinned_to_a_commit_with_its_version() -> None:
    """A tag is a pointer its publisher can move, a commit is not.

    The version comment is what Dependabot reads to raise the pin.
    """
    pinned = re.compile(r"uses: [\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$")
    loose = [
        f"{workflow.name}: {line.strip()}"
        for workflow in (REPO / ".github" / "workflows").glob("*.yml")
        for line in workflow.read_text(encoding="utf-8").splitlines()
        if "uses:" in line and not pinned.search(line)
    ]

    assert loose == []


def test_every_image_the_build_pulls_is_pinned_by_digest() -> None:
    """By tag for the reader and Dependabot, by digest for the content."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    pulled = re.findall(r"^(?:FROM|COPY --from=)\s*(\S+)", dockerfile, re.MULTILINE)
    # A stage of this file is named without a registry or a tag.
    external = [image for image in pulled if ":" in image or "/" in image]

    assert len(external) == 3
    assert all(re.search(r":[\w.-]+@sha256:[0-9a-f]{64}$", image) for image in external)


def test_every_image_is_pulled_where_dependabot_reads() -> None:
    """By a FROM line. Dependabot does not see an image in `COPY --from=`."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    copied = re.findall(r"^COPY --from=(\S+)", dockerfile, re.MULTILINE)

    assert copied
    assert all(":" not in source and "/" not in source for source in copied)


def test_no_frontend_is_pulled_by_a_moving_tag() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert not re.search(r"^#\s*syntax=", dockerfile, re.MULTILINE)


def test_every_build_and_dependabot_name_the_dockerfile() -> None:
    """It is not where Docker looks by itself, so each of them has to say so.

    A build that forgets fails loudly. Dependabot pointed at a folder without
    a Dockerfile does not: it proposes nothing, and the base image ages.
    """
    relative = DOCKERFILE.relative_to(REPO).as_posix()
    folder = DOCKERFILE.parent.relative_to(REPO).as_posix()
    github = REPO / ".github"
    ci = (github / "workflows" / "ci.yml").read_text(encoding="utf-8")
    publish = (github / "workflows" / "publish.yml").read_text(encoding="utf-8")
    dependabot = (github / "dependabot.yml").read_text(encoding="utf-8")

    assert ci.count(f"-f {relative} ") == 1
    assert ci.count(f"file: {relative}\n") == 1
    assert publish.count(f"file: {relative}\n") == 1
    assert f'directory: "/{folder}"' in dependabot


def _services(compose: Path) -> dict[str, str]:
    """Each service's block of a Compose file, by name, comments dropped.

    Read as text rather than parsed: a YAML parser is not a dependency of this
    project, and these files are written by hand in one shape.
    """
    text = compose.read_text(encoding="utf-8")
    body = text.split("\nservices:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    lines = [line for line in body.splitlines() if not line.strip().startswith("#")]
    blocks = re.split(r"^  ([a-z][\w-]*):$", "\n".join(lines), flags=re.MULTILINE)
    return dict(zip(blocks[1::2], blocks[2::2], strict=True))


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda path: path.parent.name)
def test_compose_caps_the_log_docker_keeps(compose: Path) -> None:
    """Five files of 10 MB, the json-file driver's own rotation.

    Without it Docker keeps every access line for the life of the container,
    and a restart is the same container.
    """
    text = compose.read_text(encoding="utf-8")

    block = re.search(r"^x-logging: &logging\n((?:  .*\n)+)", text, flags=re.MULTILINE)
    assert block is not None, "the shared logging block is gone"
    assert "driver: json-file" in block.group(1)
    assert 'max-size: "10m"' in block.group(1)
    assert 'max-file: "5"' in block.group(1)


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda path: path.parent.name)
def test_every_compose_service_uses_the_log_cap(compose: Path) -> None:
    """A service added later without the reference would log without limit."""
    services = _services(compose)

    assert list(services) == ["benethos-lexware-office-mcp", "setup"]
    assert all("\n    logging: *logging\n" in block for block in services.values())


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda path: path.parent.name)
def test_every_compose_port_is_published_on_the_loopback(compose: Path) -> None:
    """A bearer token guards against this machine's processes, not a network."""
    text = compose.read_text(encoding="utf-8")
    published = re.findall(r'^\s+- "([^"]*:\d+)"$', text, flags=re.MULTILINE)

    assert len(published) == 2
    assert all(port.startswith("127.0.0.1:") for port in published)


def test_development_and_production_run_the_server_alike() -> None:
    """The same settings pinned, so trying a change tries what runs.

    The comments explaining them live in the production file only.
    """
    development, production = (_services(path) for path in COMPOSE_FILES)

    for name in ("benethos-lexware-office-mcp", "setup"):
        for section in ("environment", "command", "volumes"):
            pattern = rf"^    {section}:\n((?:      .*\n)+)"
            ours = re.search(pattern, development[name] + "\n", flags=re.MULTILINE)
            theirs = re.search(pattern, production[name] + "\n", flags=re.MULTILINE)
            assert (ours and ours.group(1)) == (theirs and theirs.group(1)), (
                f"{name} differs in {section}"
            )


HARDENING = (
    "\n    read_only: true\n",
    "\n    tmpfs:\n      - /tmp\n",
    "\n    cap_drop:\n      - ALL\n",
    "\n    security_opt:\n      - no-new-privileges:true\n",
)


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda path: path.parent.name)
def test_every_compose_service_is_hardened(compose: Path) -> None:
    """Nothing written but the volumes and /tmp, and no capability kept.

    Measured 2026-10-08 against a test account: the token, the policy, a
    restart on a changed .env, a download and its rendering all work so.
    """
    for name, block in _services(compose).items():
        missing = [line.strip() for line in HARDENING if line not in block + "\n"]
        assert not missing, f"{name} lacks {missing}"


def test_production_runs_the_published_image_at_the_named_version() -> None:
    services = _services(COMPOSE_FILES[1])
    image = "image: ghcr.io/benethos-hub/benethos-lexware-office-mcp:${LXO_VERSION:?"

    assert all(image in block for block in services.values())
    assert all("build:" not in block for block in services.values())


def test_development_builds_the_image_from_this_checkout() -> None:
    services = _services(COMPOSE_FILES[0])
    dockerfile = DOCKERFILE.relative_to(REPO).as_posix()

    assert all(f"dockerfile: {dockerfile}\n" in block for block in services.values())
    assert all("ghcr.io" not in block for block in services.values())


def test_development_and_production_keep_apart() -> None:
    """Two projects, so a trial never reaches the key, token or tools in use."""
    names = [
        re.search(r"^name: (\S+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
        for path in COMPOSE_FILES
    ]

    assert [match and match.group(1) for match in names] == [
        "benethos-lexware-office-mcp-dev",
        # What the Compose file in the repository root was called, so the
        # volumes it made carry over.
        "benethos-lexware-office-mcp",
    ]


def test_the_readme_run_example_caps_the_log_as_well() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    assert "--log-opt max-size=10m --log-opt max-file=5" in readme


def test_the_allowed_hosts_example_is_the_compose_service(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The help named the service by the image's old name after both moved."""
    production = (CONTAINERS / "production" / "compose.yaml").read_text(
        encoding="utf-8"
    )
    found = re.search(r'LXO_MCP_ALLOWED_HOSTS: "([^"]+)"', production)
    assert found, "production names its own host"

    with pytest.raises(SystemExit):
        cli.main(["--help"])

    assert f"example {found.group(1)}" in " ".join(capsys.readouterr().out.split())
