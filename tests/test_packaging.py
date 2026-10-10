"""What the package ships, and what the documentation says it is.

Two kinds of thing that break without breaking anything: a file that quietly
stops being packed, and a version quoted as an example that nobody thought to
move at release time.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

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
    # The MCP Registry entry: its own version and the PyPI package's, then
    # the image tag, which carries the version in place of a field of its own.
    (".github/publish/mcp-registry/server.json", r'"version": "(\d+\.\d+\.\d+)"'),
    (".github/publish/mcp-registry/server.json", r'-mcp:(\d+\.\d+\.\d+)"'),
    # The bundle the entry offers, as a release asset: its tag and file name.
    (".github/publish/mcp-registry/server.json", r"/download/v(\d+\.\d+\.\d+)/"),
    (".github/publish/mcp-registry/server.json", r"-mcp-(\d+\.\d+\.\d+)\.mcpb"),
    # The Claude Desktop bundle's manifest, committed as it ships.
    (".github/publish/mcpb/manifest.json", r'"version": "(\d+\.\d+\.\d+)"'),
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


# -- which Python versions this project claims ------------------------------

# A new Python is named in several places, and each of them is one line, so
# adding it to some and forgetting the rest is easy and fails nothing: the
# classifiers say what PyPI shows, the matrix what is tested, the coverage
# step where the floor is held, the lowest-versions job and requires-python
# where support begins, and CLAUDE.md what a developer sets up.


def _versions(text: str) -> list[str]:
    return sorted(set(re.findall(r"3\.\d+", text)), key=lambda v: int(v[2:]))


def _python_claims(pyproject: str, ci: str, claude: str) -> list[str]:
    """Every place that names a Python version, held against the CI matrix.

    Returns what disagrees, so that an empty list is the pass and the test
    that feeds it a matrix with one more version can see the guard fire.
    """
    import tomllib

    project = tomllib.loads(pyproject)["project"]
    matrix = re.search(r"\n {8}python-version: \[([^\]]*)\]", ci)
    if matrix is None:
        return ["ci.yml no longer has a python-version matrix"]
    tested = _versions(matrix.group(1))
    oldest, newest = tested[0], tested[-1]

    problems = []
    classified = _versions(
        " ".join(
            c
            for c in project["classifiers"]
            if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)
        )
    )
    if classified != tested:
        problems.append(f"classifiers name {classified}, the matrix tests {tested}")
    if project["requires-python"] != f">={oldest}":
        problems.append(
            f"requires-python is {project['requires-python']!r}, "
            f"the oldest tested is {oldest}"
        )
    plain = re.findall(r"if: matrix\.python-version != '([\d.]+)'\n", ci)
    measured = re.findall(
        r"if: matrix\.python-version == '([\d.]+)'\n {8}run: [^\n]*--cov-fail-under",
        ci,
    )
    if plain != [newest] or measured != [newest]:
        problems.append(
            f"coverage is measured on {measured} and skipped on all but {plain}, "
            f"the newest tested is {newest}"
        )
    lowest = re.findall(r"uv venv -p ([\d.]+) /tmp/lowest", ci)
    if lowest != [oldest]:
        problems.append(
            f"lowest-versions runs on {lowest}, the oldest tested is {oldest}"
        )
    environment = re.findall(r"Python (3\.\d+)-(3\.\d+)\.", claude)
    if environment != [(oldest, newest)]:
        problems.append(f"CLAUDE.md names {environment}, the matrix {oldest}-{newest}")
    return problems


def _python_files() -> tuple[str, str, str]:
    return (
        (REPO / "pyproject.toml").read_text(encoding="utf-8"),
        (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
        (REPO / "CLAUDE.md").read_text(encoding="utf-8"),
    )


def test_every_place_names_the_python_versions_the_matrix_tests() -> None:
    assert _python_claims(*_python_files()) == []


def test_the_python_check_would_notice_a_version_added_halfway() -> None:
    """A new Python in the matrix alone trips every other place."""
    pyproject, ci, claude = _python_files()
    newest = _versions(re.findall(r"python-version: \[([^\]]*)\]", ci)[0])[-1]
    following = f"3.{int(newest[2:]) + 1}"
    halfway = ci.replace(f'"{newest}"]', f'"{newest}", "{following}"]', 1)

    assert halfway != ci
    problems = _python_claims(pyproject, halfway, claude)

    assert [p.split(" ", 1)[0] for p in problems] == [
        "classifiers",
        "coverage",
        "CLAUDE.md",
    ]


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


def test_the_image_is_pushed_under_the_package_name_alone() -> None:
    """The repository's name got the 0.4 patch releases and none after."""
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    block = workflow.split("          images: |\n", 1)[1].split("\n          flavor:")[
        0
    ]
    images = [line.strip() for line in block.splitlines()]

    assert images == [
        "ghcr.io/${{ github.repository_owner }}/benethos-lexware-office-mcp",
    ]


def test_every_publish_job_checks_the_tag() -> None:
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("run: python3 .github/scripts/tag_matches_version.py") == 4


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
    https = ["caddy"] if compose == COMPOSE_FILES[1] else []

    assert list(services) == ["benethos-lexware-office-mcp", "setup", *https]
    assert all("\n    logging: *logging\n" in block for block in services.values())


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda path: path.parent.name)
def test_every_compose_port_is_published_on_the_loopback(compose: Path) -> None:
    """A bearer token guards against this machine's processes, not a network.

    Caddy's port is the one exception, and the one meant for other machines,
    see the next test.
    """
    services = _services(compose)
    services.pop("caddy", None)
    published = [
        port
        for block in services.values()
        for port in re.findall(r'^\s+- "([^"]*:\d+)"$', block, flags=re.MULTILINE)
    ]

    assert len(published) == 2
    assert all(port.startswith("127.0.0.1:") for port in published)


def test_only_caddy_reaches_the_network_and_only_with_https() -> None:
    """Behind its own profile, on 443 alone, with one capability added."""
    caddy = _services(COMPOSE_FILES[1])["caddy"]

    assert '\n    profiles: ["https"]\n' in caddy
    assert re.findall(r'^\s+- "([^"]*:\d+)"$', caddy, flags=re.MULTILINE) == [
        "${LXO_HTTPS_PORT:-443}:443"
    ]
    assert "\n    cap_add:\n      - NET_BIND_SERVICE\n    security_opt:" in caddy


def test_caddy_proxies_the_transport_and_nothing_else() -> None:
    """Only the MCP path, to the server's own port, never the interface."""
    caddyfile = (CONTAINERS / "production" / "Caddyfile").read_text(encoding="utf-8")

    assert "@mcp path /mcp /mcp/*" in caddyfile
    assert re.findall(r"reverse_proxy (\S+)", caddyfile) == [
        "benethos-lexware-office-mcp:8770"
    ]
    assert "8771" not in caddyfile
    assert "import tls-{$LXO_TLS:internal}" in caddyfile


def test_the_server_believes_forwarded_headers_from_caddy_alone() -> None:
    """The address in FORWARDED_ALLOW_IPS is Caddy's, in the https subnet."""
    text = COMPOSE_FILES[1].read_text(encoding="utf-8")
    caddy = _services(COMPOSE_FILES[1])["caddy"]
    trusted = re.findall(r'FORWARDED_ALLOW_IPS: "([\d.]+)"', text)
    address = re.search(r"ipv4_address: ([\d.]+)", caddy)
    subnet = re.search(r"- subnet: ([\d.]+)\.0/24", text)

    assert address and subnet
    assert trusted == [address.group(1)]
    assert address.group(1).startswith(subnet.group(1) + ".")


@pytest.mark.parametrize("compose", COMPOSE_FILES, ids=lambda path: path.parent.name)
def test_setup_names_the_port_it_is_published_on(compose: Path) -> None:
    """The address in its log is what a person opens on this machine, and
    the port inside the container is not that one."""
    setup = _services(compose)["setup"]
    published = re.search(r'- "127\.0\.0\.1:(\$\{LXO_SETUP_PORT:-\d+\}):8771"', setup)

    assert published
    assert f'- --public-port\n      - "{published.group(1)}"' in setup


def _no_defaults(block: str) -> str:
    """A service block with ``${NAME:-default}`` read as ``${NAME}``.

    The two folders publish on ports of their own by design, so where a
    command names the published port, its default is the one difference.
    """
    return re.sub(r"\$\{(\w+):-[^}]*\}", r"${\1}", block) + "\n"


def test_development_and_production_run_the_server_alike() -> None:
    """The same settings pinned, so trying a change tries what runs.

    The comments explaining them live in the production file only.
    """
    development, production = (_services(path) for path in COMPOSE_FILES)

    for name in ("benethos-lexware-office-mcp", "setup"):
        for section in ("environment", "command", "volumes"):
            pattern = rf"^    {section}:\n((?:      .*\n)+)"
            ours = re.search(pattern, _no_defaults(development[name]), re.MULTILINE)
            theirs = re.search(pattern, _no_defaults(production[name]), re.MULTILINE)
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

    assert "\n    image: caddy:2\n" in services.pop("caddy")
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


# -- the MCP Registry entry --------------------------------------------------

# An entry cannot be changed once it is published, so whatever is wrong in it
# stays wrong until the next release. The registry checks it against the
# packages only at that moment, and nothing else reads these files together.
REGISTRY_ENTRY = REPO / ".github" / "publish" / "mcp-registry" / "server.json"


def _entry() -> dict[str, Any]:
    entry: dict[str, Any] = json.loads(REGISTRY_ENTRY.read_text(encoding="utf-8"))
    return entry


def _package(registry_type: str) -> dict[str, Any]:
    [package] = [p for p in _entry()["packages"] if p["registryType"] == registry_type]
    return package


def _project() -> dict[str, Any]:
    import tomllib

    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    project: dict[str, Any] = pyproject["project"]
    return project


def _owner() -> str:
    url = _entry()["repository"]["url"]
    found = re.fullmatch(r"https://github\.com/([\w.-]+)/[\w.-]+", url)
    assert found, f"{url} is not a GitHub repository"
    return found.group(1)


def test_the_registry_entry_is_named_in_the_owners_namespace() -> None:
    """The workflow's identity may write io.github.<owner>/* and nothing else."""
    assert _entry()["name"] == f"io.github.{_owner()}/{_project()['name']}"


def test_the_registry_entry_describes_the_package_as_pypi_does() -> None:
    description = _entry()["description"]

    assert description == _project()["description"]
    assert len(description) <= 100, "the registry refuses a longer description"


def test_the_registry_entry_points_at_the_published_packages() -> None:
    """The names publish.yml uploads under, and the image without a version."""
    pypi, oci = _package("pypi"), _package("oci")
    version = benethos_lexware_office_mcp.__version__
    image = f"ghcr.io/{_owner()}/{_project()['name']}:{version}"

    assert pypi["identifier"] == _project()["name"]
    assert oci["identifier"] == image
    # The registry refuses both on an image: the tag carries the version.
    assert "version" not in oci
    assert "registryBaseUrl" not in oci


def test_the_ownership_proofs_name_the_entry() -> None:
    """Once in the README PyPI shows, once as a label in the image.

    The registry wants the name followed by a space, a line end or the end of
    a comment, so a full stop after it would fail the release.
    """
    name = _entry()["name"]
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    labels = re.findall(
        r'LABEL io\.modelcontextprotocol\.server\.name="([^"]+)"',
        DOCKERFILE.read_text(encoding="utf-8"),
    )

    assert re.findall(r"mcp-name: (\S+?)(?=\s|-->)", readme) == [name]
    assert labels == [name]


def test_the_image_entry_mounts_the_volumes_setup_writes_to() -> None:
    """Without them each start gets empty volumes, and no tool is offered.

    The names are the ones the README's `setup` command mounts, so what the
    configuration interface saves is what a client's container reads.
    """
    volume = re.search(
        r"^VOLUME (\[.*\])$", DOCKERFILE.read_text(encoding="utf-8"), re.M
    )
    assert volume, "the image declares its volumes"
    declared = json.loads(volume.group(1))
    mounts = [
        a["value"]
        for a in _package("oci")["runtimeArguments"]
        if a["name"] == "--volume"
    ]
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    assert [m.split(":", 1)[1] for m in mounts] == declared
    assert all(f"-v {m}" in readme for m in mounts)


def test_the_image_entry_runs_over_stdio() -> None:
    """The image starts the HTTP transport unless it is told otherwise."""
    oci = _package("oci")

    assert oci["transport"] == {"type": "stdio"}
    assert {"type": "named", "name": "--transport", "value": "stdio"} in oci[
        "packageArguments"
    ]


def test_the_registry_entry_asks_for_no_environment_variables() -> None:
    """A variable a client sets beats the .env, which `setup` could then not change."""
    assert all("environmentVariables" not in p for p in _entry()["packages"])


def test_the_registry_job_publishes_after_both_packages() -> None:
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    job = workflow.split("  mcp-registry-publish:", 1)[1]
    head = job.split("steps:", 1)[0]

    assert "needs: [pypi-publish, ghcr-publish, mcpb-bundle]" in head
    assert "!github.event.release.prerelease" in head
    assert "      contents: read\n      id-token: write" in head
    assert re.search(r"MCP_PUBLISHER_VERSION: v\d+\.\d+\.\d+\n", head)
    assert re.search(r"MCP_PUBLISHER_SHA256: [0-9a-f]{64}\n", head)
    assert f"entry={REGISTRY_ENTRY.relative_to(REPO).as_posix()}\n" in job
    assert './mcp-publisher publish "$entry"; then' in job


def test_the_registry_icons_are_files_in_this_repository() -> None:
    """A client fetches them from main, so each has to be there by that path.

    The PNG is rendered from the SVG by `assets/render_icon.py`, and its
    declared size is the one it has.
    """
    raw = f"https://raw.githubusercontent.com/{_owner()}/lexware-office-mcp/main/"
    icons = {icon["mimeType"]: icon for icon in _entry()["icons"]}

    assert set(icons) == {"image/svg+xml", "image/png"}
    for icon in icons.values():
        assert icon["src"].startswith(raw)
        assert (REPO / icon["src"].removeprefix(raw)).is_file(), icon["src"]

    png = (REPO / icons["image/png"]["src"].removeprefix(raw)).read_bytes()
    width, height = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert icons["image/png"]["sizes"] == [f"{width}x{height}"]


# The bundle is a release asset, and the registry accepts only the GitHub
# pattern /owner/repo/releases/download/<tag>/<file> for it, so the entry
# names the file of this very release. Its hash exists only once the release
# has built it: the committed entry holds zeros, and the publish workflow
# writes the real one with fill_bundle_checksum.py.
FILL = REPO / ".github" / "publish" / "mcp-registry" / "fill_bundle_checksum.py"


def _fill_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fill_bundle_checksum", FILL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_bundle_entry_is_this_releases_asset() -> None:
    version = benethos_lexware_office_mcp.__version__
    bundle = _package("mcpb")

    assert bundle["identifier"] == (
        f"https://github.com/{_owner()}/lexware-office-mcp/releases/download/"
        f"v{version}/{_project()['name']}-{version}.mcpb"
    )
    assert bundle["transport"] == {"type": "stdio"}
    assert "registryBaseUrl" not in bundle


def test_the_bundle_entry_holds_the_placeholder() -> None:
    """A real hash in the committed file would be the previous release's."""
    assert _package("mcpb")["fileSha256"] == _fill_script().PLACEHOLDER


def test_the_bundle_file_name_is_the_one_the_workflow_uploads() -> None:
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    named = 'versioned="benethos-lexware-office-mcp-${GITHUB_REF_NAME#v}.mcpb"'

    assert named in workflow


def test_the_bundle_checksum_is_filled_in_before_publishing() -> None:
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    job = workflow.split("  mcp-registry-publish:", 1)[1]

    assert job.index("fill_bundle_checksum.py") < job.index("mcp-publisher publish")


def test_the_checksum_is_written_for_the_named_file_only(tmp_path: Path) -> None:
    version = benethos_lexware_office_mcp.__version__
    entry = tmp_path / "server.json"
    entry.write_text(REGISTRY_ENTRY.read_text(encoding="utf-8"), encoding="utf-8")
    bundle = tmp_path / f"benethos-lexware-office-mcp-{version}.mcpb"
    bundle.write_bytes(b"bundle bytes")

    digest = _fill_script().fill(entry, bundle)

    written = json.loads(entry.read_text(encoding="utf-8"))
    [package] = [p for p in written["packages"] if p["registryType"] == "mcpb"]
    assert (
        package["fileSha256"] == digest == hashlib.sha256(b"bundle bytes").hexdigest()
    )
    # The rest of the entry survives the rewrite, the dash included.
    assert written["description"] == _entry()["description"]
    with pytest.raises(SystemExit, match="placeholder"):
        _fill_script().fill(entry, bundle)
    other = tmp_path / "benethos-lexware-office-mcp-0.0.1.mcpb"
    other.write_bytes(b"x")
    entry.write_text(REGISTRY_ENTRY.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(SystemExit, match="not the file"):
        _fill_script().fill(entry, other)


def test_dropping_the_bundle_keeps_pypi_and_the_image(tmp_path: Path) -> None:
    entry = tmp_path / "server.json"
    entry.write_text(REGISTRY_ENTRY.read_text(encoding="utf-8"), encoding="utf-8")

    _fill_script().drop(entry)

    kept = json.loads(entry.read_text(encoding="utf-8"))
    assert [p["registryType"] for p in kept["packages"]] == ["pypi", "oci"]
    assert kept["description"] == _entry()["description"]
    with pytest.raises(SystemExit, match="no bundle"):
        _fill_script().drop(entry)


def test_a_refused_bundle_still_leaves_the_version_listed() -> None:
    """The registry takes an entry whole or not at all.

    After the retries the bundle is dropped and the rest published, and the
    job still fails, so the refusal is looked at.
    """
    workflow = (REPO / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    step = workflow.split("- name: Publish server.json", 1)[1]
    retries = step.index("done")
    dropped = step.index("--drop")
    republished = step.index('./mcp-publisher publish "$entry"', dropped)

    assert retries < dropped < republished < step.index("exit 1", republished)
