"""What never belongs in a versioned file, checked over every tracked file.

The pre-commit hook in .githooks/ looks at the lines a commit adds, and only
where it is enabled. This test reads the files git tracks, on every run of
the suite and so in CI, and fails on:

- a file that holds configuration or a real record: a settings file other
  than the example, the policy file, the saved profiles, a download, a PDF,
- an e-mail address on a domain that is not reserved for examples,
- a path of a machine or of a user, also in the form Git Bash and WSL
  write it,
- a credential in the forms the hook knows: a token by its prefix, and a
  value given to a name such as ``*_KEY`` or ``token``.

It holds no list of names: a list of the projects or the people to keep out
would publish what it is meant to keep out. A line that must show such a
form ends with ``pragma: allowlist secret``, or follows a comment line that
says only that, where a formatter would move a trailing comment away from
the value. The hook reads both the same way. A finding names the file, the
line and the rule, never the text. See CLAUDE.md, golden rules 6 and 7.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from functools import cache
from pathlib import Path, PurePosixPath

import pytest

REPO = Path(__file__).resolve().parents[1]
ALLOW = "pragma: allowlist secret"

# Domains reserved for examples and tests (RFC 2606, RFC 6761), and the
# addresses a commit trailer or GitHub names on purpose.
RESERVED_SUFFIXES = (".example", ".test", ".invalid", ".localhost")
RESERVED_DOMAINS = ("example.com", "example.org", "example.net")
ALLOWED_ADDRESSES = frozenset({"noreply@anthropic.com"})
NOREPLY_DOMAIN = "users.noreply.github.com"

# Something before the @, so a decorator such as @pytest.fixture is no
# address. A domain may hold letters beyond ASCII.
ADDRESS = re.compile(
    r"(?<![A-Za-z0-9._%+*-])([A-Za-z0-9._%+*-]+)@"
    r"((?:(?:[^\W_]|[*-])+\.)+[^\W\d_]{2,})\b"
)
# A user's folder on Windows, macOS and Linux, a drive as WSL and Git Bash
# mount it, and any drive path but the programs' folders, which a script may
# name on purpose. A letter after a backslash is a regular expression, as
# \d:\d.
PATH = re.compile(
    r"[A-Za-z]:[\\/]+Users[\\/]|(?<![\w.])/Users/\w|(?<![\w.])/home/\w"
    r"|(?<![\w.])/mnt/[a-z]/"
    r"|(?<![\w.])/[A-Za-z]/(?:Users|home|projects)/\w"
    r"|(?<![\w\\])[A-Za-z]:[\\/]+(?!Program Files|Windows\b)\w"
)
CREDENTIAL = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{16,}|\bsk-[A-Za-z0-9_-]{20,}"
    r"|Bearer [A-Za-z0-9._-]{16,}|\bgh[pousr]_[A-Za-z0-9]{16,}"
    r"|glpat-[A-Za-z0-9_-]{16,}|\bAKIA[0-9A-Z]{16}\b"
    r"|BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY"
    # A name that ends in TOKEN, SECRET, PASSWORD or _KEY, maybe with more
    # parts such as _FILE, then the value. _KEYWORD is no such name.
    r"|(?:TOKEN|SECRET|PASSWORD|_KEY)(?:_[A-Z]+)*\s*[:=]\s*[\"']?"
    r"[A-Za-z0-9+_-][A-Za-z0-9+/_.-]{11,}"
)
# The same in any case, as JSON and YAML write it: a quoted value, or a
# bare one that ends the line or a word. A bare value with a dot or a
# bracket is code, such as token = secrets.token_urlsafe(32).
NAMED = re.compile(
    r"(?:^|[^a-z0-9])[\"']?[a-z0-9_]*(?:token|secret|password|passwd|_key)[\"']?"
    r"\s*[:=]\s*"
    r"(?:[\"'][A-Za-z0-9+_-][A-Za-z0-9+/_.-]{11,}"
    r"|[A-Za-z0-9+_-][A-Za-z0-9+/_-]{11,}(?:\s|$))",
    re.IGNORECASE,
)
# A setting's own name as a value, API_KEY = "LXO_MCP_API_KEY", is a name
# and not a key. It is shortened before the two patterns above look.
SETTING_AS_VALUE = re.compile(r"([:=]\s*[\"']?)LXO_MCP_[A-Z0-9_]+")
# CREDENTIAL, NAMED, PATH and ADDRESS follow .githooks/pre-commit. A change
# to one changes the other.


def forbidden(name: str) -> bool:
    """Whether a tracked file is one that holds configuration or a record."""
    path = PurePosixPath(name)
    parts = path.parts
    if name.endswith(".env.example"):
        return False
    return (
        path.name == ".env"
        or path.name.startswith(".env.")
        or path.name in ("tools.json", "tool_profiles.json")
        or "downloads" in parts[:-1]
        or parts[0] in ("scratch", "dist", "build")
        or path.suffix.lower() == ".pdf"
    )


def _reserved(domain: str) -> bool:
    """Whether ``domain`` is reserved for examples, or names no domain of
    anyone: a placeholder such as ``*.domain``, one label after wildcards."""
    domain = domain.lower()
    labels = [label for label in domain.split(".") if label != "*"]
    return (
        len(labels) < 2
        or any(domain == d or domain.endswith("." + d) for d in RESERVED_DOMAINS)
        or domain.endswith(RESERVED_SUFFIXES)
    )


def addresses(line: str) -> list[str]:
    """The addresses of ``line`` on a domain not reserved for examples."""
    return [
        found.group(0)
        for found in ADDRESS.finditer(line)
        if not _reserved(found.group(2))
        and found.group(0).lower() not in ALLOWED_ADDRESSES
        and found.group(2).lower() != NOREPLY_DOMAIN
    ]


def allowed_by(previous: str) -> bool:
    """Whether ``previous`` is a comment line that allows the next one."""
    text = previous.strip()
    return text.startswith("#") and text.endswith(ALLOW)


def problems(line: str) -> list[str]:
    """The rules one line breaks, by name."""
    if ALLOW in line:
        return []
    found = ["address"] * len(addresses(line))
    found += ["path"] * len(PATH.findall(line))
    named = SETTING_AS_VALUE.sub(r"\1LXO", line)
    found += ["credential"] * (
        len(CREDENTIAL.findall(named)) + len(NAMED.findall(named))
    )
    return found


@cache
def tracked() -> tuple[str, ...]:
    """The paths git tracks."""
    git = shutil.which("git")
    if git is None:
        pytest.fail("the repository content is read through git, which is missing")
    done = subprocess.run(
        [git, "ls-files", "-z"], cwd=REPO, capture_output=True, check=False
    )
    if done.returncode != 0:
        pytest.fail("the repository content is read through git: not a checkout")
    return tuple(filter(None, done.stdout.decode().split("\0")))


def test_no_tracked_file_holds_configuration_or_a_record() -> None:
    names = tracked()

    assert len(names) > 100, "git listed too few files to be this repository"
    assert [n for n in names if forbidden(n)] == []


def test_no_tracked_line_holds_an_address_a_path_or_a_key() -> None:
    hits = []
    for name in tracked():
        path = REPO / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        previous = ""
        text = data.decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if not allowed_by(previous):
                hits += [f"{name}:{number}: {r}" for r in sorted(set(problems(line)))]
            previous = line

    assert hits == [], "\n".join(hits)


# -- the rules themselves, on lines put together here so the scan above
# -- does not find them in this file.

AT = "@"
SEP = "\\"


@pytest.mark.parametrize(
    "name",
    [
        "config/.env",
        ".env",
        ".env.local",
        "config/tools.json",
        "tool_profiles.json",
        "x/downloads/invoice-1.xml",
        "scratch/notes.txt",
        "dist/package.whl",
        "receipt.PDF",
    ],
)
def test_a_file_of_configuration_or_records_is_found(name: str) -> None:
    assert forbidden(name)


@pytest.mark.parametrize(
    "name",
    [
        "containers/production/.env.example",
        "src/benethos_lexware_office_mcp/env.sample",
        "src/benethos_lexware_office_mcp/files/downloads.py",
        "docs/concept/tools.md",
    ],
)
def test_a_file_that_belongs_passes(name: str) -> None:
    assert not forbidden(name)


@pytest.mark.parametrize(
    "line",
    [
        "billing" + AT + "real-host.com",
        "Owner <someone" + AT + "provider.net>",
        "rechnung" + AT + "müller.de",
    ],
)
def test_an_address_on_a_real_domain_is_found(line: str) -> None:
    assert problems(line) == ["address"]


@pytest.mark.parametrize(
    "line",
    [
        "a" + AT + "example.com",
        "b" + AT + "files.example.com",
        "billing" + AT + "hosting.example",
        "someone" + AT + "nowhere.invalid",
        "Co-Authored-By: Claude <noreply" + AT + "anthropic.com>",
        "1+someone" + AT + "users.noreply.github.com",
        AT + "pytest.mark.parametrize",
        "uses: actions/checkout" + AT + "v7.0.1",
    ],
)
def test_an_address_for_examples_passes(line: str) -> None:
    assert problems(line) == []


@pytest.mark.parametrize(
    "line",
    [
        "C:" + SEP + "Users" + SEP + "someone" + SEP + "x",
        "D:" + SEP + "projects" + SEP + "other",
        "see /" + "home/someone/cache",
        "see /" + "d/projects/other",
        "see /" + "mnt/c/temp",
    ],
)
def test_a_path_of_a_machine_is_found(line: str) -> None:
    assert problems(line) == ["path"]


@pytest.mark.parametrize(
    "line",
    [
        "C:" + SEP + "Program Files" + SEP + "uv" + SEP + "uv.exe",
        "https://example.com/a and http://x.org/b",
        "re.compile(r'" + SEP + "d:" + SEP + "d')",
        "cache under ~/.cache/benethos-lexware-office-mcp",
    ],
)
def test_a_path_that_names_no_machine_passes(line: str) -> None:
    assert problems(line) == []


@pytest.mark.parametrize(
    "line",
    [
        "LXO_MCP_API" + "_KEY=abcd1234efgh5678ijkl",
        '"bearer_' + 'token": "abcd1234efgh5678ijkl"',
        "Authorization: Bear" + "er abcd1234efgh5678ijkl",
        "gh" + "p_abcdefghijklmnop1234",
    ],
)
def test_a_credential_is_found(line: str) -> None:
    assert "credential" in problems(line)


@pytest.mark.parametrize(
    "line",
    [
        'API_KEY = "LXO_MCP_API' + '_KEY"',
        "token = secrets.token_urlsafe(32)",
        "LXO_MCP_API" + "_KEY=",
        "token = 'abcd1234efgh5678ijkl'  # " + ALLOW,
    ],
)
def test_a_name_code_or_an_allowed_line_passes(line: str) -> None:
    assert problems(line) == []


def test_a_comment_line_allows_the_line_after_it() -> None:
    assert allowed_by("        # " + ALLOW)
    assert not allowed_by('token = "x"  # ' + ALLOW)
    assert not allowed_by("# a comment about something else")
