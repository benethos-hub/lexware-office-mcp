"""Carrying one policy file to another installation.

The file itself, in the shape ``tools.json`` already has: one flag per tool,
nothing around it. No wrapper, no format version, no metadata — so a file
downloaded here can be dropped straight into another installation's config
directory or named with ``--tools-file``, and a file written by the command
line can be read here. Anything wrapped would have been a second format for
the same thing.

**Reading one follows the rule the command line calls `sync`.** A tool the
file does not name is **off**, which is what the policy file means everywhere
else in this project, so a file written before a tool existed leaves that tool
switched off rather than guessing. The interface says how many those are
instead of letting them pass unmentioned, and a name that is no longer a tool
is dropped the same way ``--tools sync`` drops it.
"""

from __future__ import annotations

import json

__all__ = ["TransferError", "dumps", "parse"]


class TransferError(ValueError):
    """The file is not a policy file."""


def dumps(flags: dict[str, bool]) -> str:
    """The flags as a policy file, byte for byte what ``ToolPolicy`` writes."""
    return (
        json.dumps(
            {name: bool(flag) for name, flag in sorted(flags.items())},
            indent=1,
            ensure_ascii=False,
        )
        + "\n"
    )


def parse(text: str) -> dict[str, bool]:
    """Read a policy file, or explain in one sentence why it is not one.

    Every value is taken as a flag, because that is how the server reads the
    file too: :meth:`ToolPolicy._stored` puts ``bool()`` around whatever it
    finds, and a reader that was stricter than the thing it feeds would refuse
    files that work.
    """
    try:
        data = json.loads(text)
    except ValueError:
        raise TransferError("Das ist keine gültige JSON-Datei.") from None
    if not isinstance(data, dict):
        raise TransferError(
            "Eine Rechtedatei ist ein JSON-Objekt aus Tool-Namen und true oder false."
        )
    if not data:
        raise TransferError("Die Datei nennt kein einziges Tool.")
    return {str(name): bool(flag) for name, flag in data.items()}
