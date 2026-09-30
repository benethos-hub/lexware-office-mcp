"""The tool policy file, and a client being told the tool list changed."""

from __future__ import annotations

import logging
from pathlib import Path

from ._describe import describe
from .output import PACKAGE

__all__ = [
    "list_changed",
    "not_a_flag",
    "not_an_object",
    "session_dropped",
    "unreadable",
]

_log = logging.getLogger(f"{PACKAGE}.policy")

# JSON's own names, since the file is JSON and a person wrote it.
_JSON_TYPES = {
    str: "a string",
    int: "a number",
    float: "a number",
    type(None): "null",
    list: "a list",
    dict: "an object",
}


def unreadable(path: Path, error: BaseException) -> None:
    _log.warning(
        "Unreadable tool policy %s, so nothing is enabled: %s", path, describe(error)
    )


def not_an_object(path: Path) -> None:
    _log.warning("Tool policy %s is not an object, so nothing is enabled.", path)


def not_a_flag(source: str, tool: str, found: object) -> None:
    """A flag that is not a boolean, named by its JSON type."""
    _log.warning(
        "%s: %r is %s, which is not true or false - reading it as false.",
        source,
        tool,
        _JSON_TYPES.get(type(found), "not a boolean"),
    )


def list_changed(sessions: int) -> None:
    _log.info("The tool list changed, %d sessions told", sessions)


def session_dropped(error: BaseException) -> None:
    """Debug only: a client that went away is normal."""
    _log.debug("A session could not be told and was dropped: %s", describe(error))
