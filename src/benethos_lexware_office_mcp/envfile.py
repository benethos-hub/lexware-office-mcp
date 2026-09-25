"""Reading and writing a ``.env`` file, in one place.

The server only ever reads. The configuration interface writes, and writes
into a file a person keeps by hand — with their comments in it, their
ordering, and settings this project knows nothing about. So an update edits
the lines it has something to say about and leaves every other byte alone.

Both halves live here so that the parser the server trusts and the parser the
interface shows a value from are the same function. Two of them would agree
until the day a quoted value or an ``export`` prefix made them disagree, and
the interface would then display something the server does not read.
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from pathlib import Path

__all__ = ["read_env_file", "update_env_file"]


def read_env_file(path: Path) -> dict[str, str]:
    """Read a minimal ``.env`` file.

    Supports ``KEY=value``, ``export KEY=value``, ``#`` comments and quoted
    values. Anything else is ignored rather than raising, because a malformed
    line in a config file must not stop the server from starting.
    """
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        key, value = _split(raw)
        if key:
            values[key] = value
    return values


def update_env_file(path: Path, updates: dict[str, str]) -> None:
    """Merge ``updates`` into the file at ``path``, creating it if needed.

    A key already in the file is rewritten where it stands, so the comment
    above it still describes the line below it. A key that is not becomes a
    new line at the end. Comments, blank lines, ordering and every setting not
    named in ``updates`` survive untouched.

    A value is written as it was given. Nothing here quotes or escapes,
    because the settings this project has are keys, URLs, paths and numbers,
    and a value that would need quoting is a mistake worth seeing rather than
    hiding. **A line break is refused outright**, key or value: written as
    given it would end the line, and whatever followed would be a setting of
    its own - ``LXO_MCP_API_KEY`` included, which the interface otherwise
    only writes after checking it.

    The file holds the API key, so a new one is created readable by its owner
    only, and an existing one keeps the permissions it had. It is written to
    a temporary file beside it and moved into place, so a crash or a full
    disk leaves the old file rather than half of a new one.
    """
    for key, value in updates.items():
        if not _one_line(key) or not _one_line(value):
            # The value is never quoted back: it may be the API key.
            name = key if _one_line(key) else "a setting name"
            raise ValueError(
                f"{name} contains a line break, which a .env cannot hold. "
                "Nothing was written."
            )
    remaining = dict(updates)
    lines: list[str] = []
    for raw in _existing_lines(path):
        key, _ = _split(raw)
        if key and key in remaining:
            lines.append(f"{key}={remaining.pop(key)}")
        else:
            lines.append(raw)
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    _replace(path, ("\n".join(lines) + "\n").encode("utf-8"))


def _one_line(text: str) -> bool:
    """Whether ``text`` stays on one line, by the rule the reader splits on.

    ``str.splitlines`` breaks on more than ``\\n`` and ``\\r`` - a form feed,
    a vertical tab, U+2028 and a few others - so the check asks it directly
    rather than listing characters that would one day be incomplete.
    """
    return "\x00" not in text and len(f"a{text}a".splitlines()) == 1


def _replace(path: Path, content: bytes) -> None:
    """Write ``content`` to ``path`` atomically, owner-only when new."""
    # A link is followed, so the file it names is updated and the link stays.
    target = path.resolve() if path.is_symlink() else path
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode: int | None = stat.S_IMODE(target.stat().st_mode)
    except OSError:
        mode = None
    # mkstemp creates the file 0600, which is what a new .env should be.
    handle, temp = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        if mode is not None:
            os.chmod(temp, mode)
        os.replace(temp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise


def _existing_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _split(raw: str) -> tuple[str, str]:
    """One line to a key and a value, or two empty strings if it is neither."""
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        return "", ""
    line = line.removeprefix("export ").lstrip()
    key, _, value = line.partition("=")
    key, value = key.strip(), value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return key, value
