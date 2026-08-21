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
    hiding.
    """
    remaining = dict(updates)
    lines: list[str] = []
    for raw in _existing_lines(path):
        key, _ = _split(raw)
        if key and key in remaining:
            lines.append(f"{key}={remaining.pop(key)}")
        else:
            lines.append(raw)
    lines.extend(f"{key}={value}" for key, value in remaining.items())

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
