"""The prompts a client offers a person: recipes that chain the tools.

A prompt asks Lexware nothing. It returns one user message that tells the
model which tools to call, in which order, and which traps of the books to
mind, so a person who picks "Missing receipts" and types a month gets the
same careful sequence every time. Every recipe reads and none writes.

A prompt is offered whatever the policy file says. It reaches no data and
calls nothing, the person picks it and the model is left with the tools the
file allows, so a recipe whose tool is withheld says so rather than working
around it. See SPECS.md section 8.

Each prompt is a subclass of ``_base.Prompt`` in a module of its own name, as
each tool sits in the module of its group. The text names tools and fields in
backticks, and ``tests/test_prompts.py`` checks every such name against the
registered tools and what they answer with, so a renamed tool cannot leave a
recipe pointing nowhere. The prompt that opens the configuration interface is
not one of these: it starts a process and exists over stdio only, see
:mod:`..transport.setup_prompt`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .contact_overview import ContactOverview
from .missing_receipts import MissingReceipts
from .open_items import OpenItems

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from mcp.server.mcpserver import MCPServer

__all__ = ["register_prompts"]

# The order of this tuple is the order a client lists the prompts in.
_PROMPTS = (
    OpenItems(),
    MissingReceipts(),
    ContactOverview(),
)


def register_prompts(server: MCPServer) -> None:
    """Register every recipe with ``server``, in the order a client lists them."""
    for prompt in _PROMPTS:
        prompt.register(server)
