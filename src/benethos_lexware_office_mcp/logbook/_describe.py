"""What of an exception may go into a line.

An exception's text is the one thing a line must not simply print: this
server's own messages quote what the model sent, and a library's can quote a
URL. What is read here is the class and the parts known to hold no input.
"""

from __future__ import annotations

import json

__all__ = ["describe"]


def describe(error: BaseException) -> str:
    """The class of ``error``, and what of it is safe to say."""
    name = type(error).__name__
    if isinstance(error, json.JSONDecodeError):
        return f"{name} at line {error.lineno} column {error.colno}"
    if isinstance(error, OSError) and error.strerror:
        return f"{name}, {error.strerror}"
    return name
