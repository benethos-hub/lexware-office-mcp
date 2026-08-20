"""Shared registration helper for the tool modules.

Its own module rather than ``tools/__init__``, because the package init
imports every tool module and those modules need this helper — importing it
from the init would close the circle.
"""

from __future__ import annotations

import inspect
from typing import Any

from mcp.server.mcpserver import MCPServer

__all__ = ["register_tool"]


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
