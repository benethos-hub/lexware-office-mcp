"""What of an exception or an id may go into a line.

An exception's text is the one thing a line must not simply print: this
server's own messages quote what the model sent, and a library's can quote a
URL. What is read here is the class and the parts known to hold no input.

An id is the model's argument or the API's answer. A Lexware id is a UUID,
and a UUID cannot carry a name, so that is the shape a line accepts.
"""

from __future__ import annotations

import json
import re

__all__ = ["UUID", "describe", "shown_id"]

UUID = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def shown_id(value: str) -> str:
    """``value`` if it is a UUID, else a mark that something else was there."""
    return value if UUID.fullmatch(value) else "~"


def describe(error: BaseException) -> str:
    """The class of ``error``, and what of it is safe to say.

    For one of this server's errors that is the status the API answered with
    and the API's own codes, set by ``errors.from_response``, and whether a
    write's outcome is unknown.
    """
    name = type(error).__name__
    if isinstance(error, json.JSONDecodeError):
        return f"{name} at line {error.lineno} column {error.colno}"
    if isinstance(error, OSError) and error.strerror:
        return f"{name}, {error.strerror}"
    parts = [name]
    status = getattr(error, "status", None)
    if isinstance(status, int):
        parts.append(str(status))
    code = getattr(error, "code", "")
    if isinstance(code, str) and code:
        parts.append(code)
    text = " ".join(parts)
    if getattr(error, "outcome_unknown", False) is True:
        text += ", outcome unknown"
    return text
