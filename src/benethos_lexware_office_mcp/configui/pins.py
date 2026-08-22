"""Which files this interface works on, remembered between runs.

The MCP server is started by a client, usually with ``--env-file`` and
``--tools-file`` in its arguments. The interface is started by a person, in
another process, and **cannot see those arguments**. Without help it searches
for its own files and edits whichever it finds — which is silently the wrong
ones whenever the client named different ones.

So the two paths can be written down once, here, and the interface uses them
from then on. It answers exactly one question: *which files does the
configuration interface act on.*

**It never decides anything for the server.** A pointer file that could
redirect the policy the server enforces would be a second gate beside
``tools.json``, and section 9.2 has one. The server ignores this file and
always will.

**Fixed location, deliberately not searched.** It lives in the per-user
configuration directory and nowhere else. A pointer file that had to be found
first would need a pointer of its own, and the whole point is that it can be
read with no arguments at all.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import config_dir

__all__ = ["PINS_NAME", "Pins", "pins_file", "read_pins", "write_pins"]

logger = logging.getLogger(__name__)

PINS_NAME = "setup.json"


@dataclass(frozen=True, slots=True)
class Pins:
    """The two paths, either of which may be unset."""

    env_file: Path | None = None
    tools_file: Path | None = None

    def __bool__(self) -> bool:
        return self.env_file is not None or self.tools_file is not None


def pins_file() -> Path:
    """Where the pointers live. One place, never searched for."""
    return config_dir() / PINS_NAME


def read_pins(path: Path | None = None) -> Pins:
    """The remembered paths, or empty ones.

    An unreadable file is worth a line on stderr and nothing more: the
    interface then searches as it would have anyway, which is a working
    state rather than a broken one.
    """
    target = path or pins_file()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Pins()
    except (OSError, ValueError) as exc:
        logger.warning("Unreadable setup pointers at %s: %s", target, exc)
        return Pins()
    if not isinstance(data, dict):
        return Pins()
    return Pins(
        env_file=_as_path(data.get("envFile")),
        tools_file=_as_path(data.get("toolsFile")),
    )


def write_pins(pins: Pins, path: Path | None = None) -> Path:
    """Write the pointers, dropping the ones that are unset."""
    target = path or pins_file()
    document = {
        key: str(value)
        for key, value in (("envFile", pins.env_file), ("toolsFile", pins.tools_file))
        if value is not None
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return target


def _as_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value.strip()).expanduser()
