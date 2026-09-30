"""Shared registration helper for the tool modules.

Its own module rather than ``tools/__init__``, because the package init
imports every tool module and those modules need this helper — importing it
from the init would close the circle.
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, NamedTuple

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from .. import logbook
from ..errors import ConflictError, ToolError
from ..policy import ToolPolicy, guarded, known_tools
from ..records.types import DocumentType
from ..settings import MAX_PAGE_SIZE

__all__ = [
    "DocumentIdField",
    "DocumentTypeField",
    "PageNumber",
    "PageSize",
    "register_tool",
    "require_version",
]

# Every list tool takes the same two parameters, and every parameter
# description is sent to the model on every request. Declaring them once keeps
# the wording identical across tools and pays for it once.
PageNumber = Annotated[
    int,
    Field(
        description=(
            "Zero-based page number. Read the `page` block of the previous "
            "result before asking for another one, rather than paging blindly."
        ),
        ge=0,
    ),
]

PageSize = Annotated[
    int,
    Field(
        description=(
            "Rows per page. A larger page costs the same single API call but "
            "more of the answer's token budget, so raise it only when the "
            "whole list is genuinely needed."
        ),
        ge=1,
        le=MAX_PAGE_SIZE,
    ),
]

# The sales document tools and `download_document` address the same seven
# documents, so they share these two as well, for the same reason.
DocumentTypeField = Annotated[
    DocumentType,
    Field(
        description=(
            "Which kind of document this is. Take it from the `voucherType` "
            "search_vouchers reported, where a sales invoice is 'invoice'."
        )
    ),
]

DocumentIdField = Annotated[
    str,
    Field(description="The document's Lexware id, as returned by search_vouchers."),
]


# Two tools answer without reaching the API at all: `get_deeplink` builds a
# URL out of ids the caller already holds, and `read_download` reads a file
# this server put on disk earlier. Everything else talks to Lexware.
_CLOSED_WORLD = frozenset({"get_deeplink", "read_download"})


def _annotations(name: str) -> ToolAnnotations | None:
    """The MCP hints for one tool, derived from what `classify` recorded.

    Derived rather than declared per tool, so a tool cannot end up saying one
    thing to the policy file and another to the client. The protocol calls
    these hints and warns that a client must not trust them from an untrusted
    server, which is why nothing here enforces anything: the policy file
    decides what may be called, see :mod:`..policy`.
    """
    meta = known_tools().get(name)
    if meta is None:  # pragma: no cover - every tool is classified
        return None
    # `open_world_hint` is only stated where it is *not* what the protocol
    # already assumes, which saves it being repeated on two dozen tools. The
    # three hints below are stated either way: a client that skips a default
    # would then read "deletes things" as nothing at all, and this list is
    # sent often enough that the difference was worth measuring - see SPECS.md
    # section 8.
    if meta.access == "read":
        return ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False if name in _CLOSED_WORLD else None,
        )
    return ToolAnnotations(
        read_only_hint=False,
        # A create only adds. An update replaces the record, because this API
        # has no patch, and a delete removes it - both destroy what was there.
        destructive_hint=meta.effect != "create",
        # A second create makes a second record: the API offers no
        # idempotency key, measured 2026-08-21, see SPECS.md section 16. A
        # repeat of an update or a delete leaves the books as they already
        # are - the update spends a version it no longer has and is refused,
        # the delete finds nothing left to remove.
        idempotent_hint=meta.effect != "create",
    )


def require_version(
    current: dict[str, Any], version: int, *, noun: str, reader: str
) -> None:
    """Refuse an update written against a version the record has moved past.

    Every update reads the record first and merges into it, so the version
    the caller quotes is checked here, before anything is sent. The API
    would refuse it too, but its wording for this is ``version:
    invalid_value`` behind a 406, and a caller told to read the record again
    with the tool that reads it can act on that.
    """
    found = current.get("version")
    if found == version:
        return
    raise ConflictError(
        f"This {noun} is at version {found}, but the update was written "
        f"against version {version}. Somebody changed it in between. Read it "
        f"again with {reader}, check whether your change still applies, then "
        "retry."
    )


def register_tool(server: MCPServer, func: Callable[..., Awaitable[Any]]) -> None:
    """Register one tool, with its description tidied first.

    Every tool is registered, whatever the policy says. What the policy
    decides is what gets **listed**, in :class:`~..server.PolicyServer`, and
    what may be **called**, in the :func:`~..policy.guarded` wrapper put
    around the function here - with the policy of *this* server, which a
    server without one does not have, and then nothing may be called.
    Deciding more here would freeze the answer at startup: a tool enabled
    afterwards was never registered, and no amount of re-reading the file
    would bring it back.

    The docstring becomes the description the model reads, and descriptions
    are sent on **every** request. Python keeps the source indentation on
    every line after the first, so registering a docstring as written pays for
    that whitespace forever. ``cleandoc`` strips the common indent and the
    trailing blank line.
    """
    if func.__doc__:
        func.__doc__ = inspect.cleandoc(func.__doc__)
    policy = getattr(server, "policy", None)
    if not isinstance(policy, ToolPolicy):
        policy = ToolPolicy()
    server.tool(annotations=_annotations(func.__name__))(logged(guarded(func, policy)))


def logged(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """``func``, writing one line on stderr for every call.

    Outside the policy guard, so a call the policy refuses is a line too. The
    line is given the tool's name, the time it took, how many API calls it
    made, and from the result the id, version, rows or size of what it read
    or wrote - see :func:`_outcome` - and never an argument's value or the
    answer itself. One of this server's errors is noted and passed on.
    Anything else passes untouched, and the SDK writes it as an error with
    its traceback.
    """
    name = func.__name__

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        with logbook.tally.counting() as tally:
            try:
                result = await func(*args, **kwargs)
            except ToolError as exc:
                logbook.calls.ended(name, exc, tally.calls, _ms(started))
                raise
        _report(name, result, kwargs, tally.calls, _ms(started))
        return result

    return wrapper


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


class _Outcome(NamedTuple):
    """What a line may say about a result, and nothing more."""

    record_id: str = ""
    version: int | None = None
    voucher: str = ""
    rows: int | None = None
    size: int | None = None


def _report(
    name: str, result: Any, kwargs: dict[str, Any], calls: int, ms: float
) -> None:
    """The line for a call that returned, by what the tool is."""
    meta = known_tools().get(name)
    out = _outcome(result, kwargs)
    if meta is None or meta.access == "read":
        logbook.calls.read(name, out.record_id, out.rows, out.size, calls, ms)
    elif meta.effect == "delete":
        logbook.calls.removed(name, out.record_id, calls, ms)
    else:
        finalized = kwargs.get("finalize") is True
        logbook.calls.wrote(
            name, out.record_id, out.version, out.voucher, finalized, calls, ms
        )


def _outcome(result: Any, kwargs: dict[str, Any]) -> _Outcome:
    """The id, version, voucher, rows or size of what a tool returned.

    A list is a count of its rows. Anything else is the record's own id
    where the result carries one - an update, a creation, a record read -
    and ``deleted`` for a delete. A download carries none, so its id is the
    one it was asked for: an argument, but a line shows only a UUID, see
    ``logbook``.
    """
    payload = (
        result.structured_content if isinstance(result, CallToolResult) else result
    )
    if not isinstance(payload, dict):
        return _Outcome()
    if "page" in payload:
        lists = [value for value in payload.values() if isinstance(value, list)]
        return _Outcome(rows=len(lists[0]) if lists else 0)
    found = payload.get("id") or payload.get("deleted")
    if found is None:
        asked = [value for key, value in kwargs.items() if key.endswith("_id")]
        found = next((value for value in asked if value), "")
    version = payload.get("version")
    size = payload.get("size")
    return _Outcome(
        record_id=str(found),
        version=version if isinstance(version, int) else None,
        voucher=str(payload.get("voucherId") or ""),
        size=size if isinstance(size, int) else None,
    )
