"""Shared registration helper for the tool modules.

Its own module rather than ``tools/__init__``, because the package init
imports every tool module and those modules need this helper — importing it
from the init would close the circle.
"""

from __future__ import annotations

import inspect
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from ..config import MAX_PAGE_SIZE

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


def register_tool(server: MCPServer, func: Any) -> None:
    """Register one tool, with its description tidied first.

    The docstring becomes the description the model reads, and descriptions
    are sent on **every** request. Python keeps the source indentation on
    every line after the first, so registering a docstring as written pays for
    that whitespace forever. ``cleandoc`` strips the common indent and the
    trailing blank line.
    """
    if func.__doc__:
        func.__doc__ = inspect.cleandoc(func.__doc__)
    server.tool()(func)
