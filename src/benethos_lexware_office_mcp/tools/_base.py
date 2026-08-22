"""Shared registration helper for the tool modules.

Its own module rather than ``tools/__init__``, because the package init
imports every tool module and those modules need this helper — importing it
from the init would close the circle.
"""

from __future__ import annotations

import inspect
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from ..config import MAX_PAGE_SIZE
from ..policy import known_tools

__all__ = ["PageNumber", "PageSize", "register_tool"]

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


def register_tool(server: MCPServer, func: Any) -> None:
    """Register one tool, with its description tidied first.

    Every tool is registered, whatever the policy says. What the policy
    decides is what gets **listed**, in :class:`~..server.PolicyServer`, and
    what may be **called**, in the wrapper `classify` puts around the
    function. Deciding it here as well would freeze the answer at startup: a
    tool enabled afterwards was never registered, and no amount of re-reading
    the file would bring it back.

    The docstring becomes the description the model reads, and descriptions
    are sent on **every** request. Python keeps the source indentation on
    every line after the first, so registering a docstring as written pays for
    that whitespace forever. ``cleandoc`` strips the common indent and the
    trailing blank line.
    """
    if func.__doc__:
        func.__doc__ = inspect.cleandoc(func.__doc__)
    server.tool(annotations=_annotations(func.__name__))(func)
