"""One line per tool call: what it read or wrote, or why it did not.

Written by the wrapper every tool is registered with, not by the tools, so no
tool can forget to report itself and none of them grows a line of logging.
The wrapper hands over what a line may carry and nothing else - the id of the
record, a count of rows, a size - and never the arguments or the answer.

Reading and writing are both ``INFO``: the log is where the account owner
sees what the assistant looked at as well as what it changed. A refusal and
a failure are ``WARNING``, and a crash is the SDK's own ``ERROR`` with its
traceback, since the wrapper lets anything that is not a
:class:`~..errors.ToolError` pass untouched.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ..errors import (
    AuthError,
    ConfigError,
    LocalFileError,
    RateLimitError,
    UpstreamError,
)
from ._describe import describe, shown_id
from .output import PACKAGE

__all__ = ["arguments_refused", "ended", "read", "removed", "wrote"]

_log = logging.getLogger(f"{PACKAGE}.tools")

# What went wrong on this side or upstream, as against a call the server or
# the API turned down. The first is something for the operator to look into,
# the second is the model asking for something it may not have or that does
# not exist.
_FAILURES = (AuthError, ConfigError, LocalFileError, RateLimitError, UpstreamError)


def _cost(calls: int, ms: float) -> str:
    return f"{calls} API call{'' if calls == 1 else 's'}, {ms:.0f} ms"


def read(
    tool: str, record_id: str, rows: int | None, size: int | None, calls: int, ms: float
) -> None:
    """A tool that changed nothing. The record, the rows or the size it read."""
    what = []
    if rows is not None:
        what.append(f"{rows} row{'' if rows == 1 else 's'}")
    elif record_id:
        what.append(shown_id(record_id))
    if size is not None:
        what.append(f"{size} bytes" if size < 1024 else f"{size / 1024:.0f} kB")
    subject = f" {', '.join(what)}" if what else ""
    _log.info("%s read%s in %s", tool, subject, _cost(calls, ms))


def wrote(
    tool: str,
    record_id: str,
    version: int | None,
    voucher: str,
    finalized: bool,
    calls: int,
    ms: float,
) -> None:
    """A record created or replaced, by id, and what became of it."""
    notes = []
    if version is not None:
        notes.append(f"version {version}")
    if finalized:
        notes.append("finalized")
    detail = f" ({', '.join(notes)})" if notes else ""
    owner = f" for voucher {shown_id(voucher)}" if voucher else ""
    _log.info(
        "%s wrote %s%s%s in %s",
        tool,
        shown_id(record_id),
        owner,
        detail,
        _cost(calls, ms),
    )


def removed(tool: str, record_id: str, calls: int, ms: float) -> None:
    _log.info("%s removed %s in %s", tool, shown_id(record_id), _cost(calls, ms))


def ended(tool: str, error: BaseException, calls: int, ms: float) -> None:
    """A tool that raised one of this server's errors: refused, or failed."""
    verb = "failed" if isinstance(error, _FAILURES) else "refused"
    _log.warning("%s %s: %s, after %s", tool, verb, describe(error), _cost(calls, ms))


def arguments_refused(tool: str, fields: Sequence[str]) -> None:
    """Arguments that did not match the schema, named by field and not by value."""
    _log.warning("%s refused: invalid %s", tool, ", ".join(fields))
