"""What every prompt shares: the base class and the rules each recipe ends with.

A prompt is a subclass of :class:`Prompt`, one per module, its module named
like the prompt. It sets ``name`` and ``title`` and writes ``render``. The
parameters of ``render`` become the arguments a client asks a person for, its
docstring the description a client shows, as a tool's do.

**A text has no branch in it.** Claude Desktop holds the text a prompt answers
with against the one its extension declares, with every argument written as
``${arguments.<name>}``, and drops an answer that differs. So an argument goes
into the text exactly as it was given, and a text says in words what an empty
one means rather than choosing another sentence for it. See SPECS.md section 8.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from mcp.server.mcpserver import MCPServer

__all__ = ["ENABLED", "RULES", "Prompt"]

# Opens every recipe. A prompt is offered whatever the policy file says, since
# it reaches no data, so the tools it names may not be there.
ENABLED = (
    "Use only the tools in your list. The account owner decides which exist, "
    "so when one named here is missing, say which one and that it can be "
    "enabled in the configuration, and leave out the step that needs it "
    "rather than working around it."
)

# Closes every recipe, so each one minds the same traps of the books.
RULES = (
    "Ids come from a search result, never from memory. Amounts are exactly "
    "what Lexware reports, each with its currency, never rounded and never "
    "converted, and a sum is formed per currency. A list answers in pages: "
    "read the `page` block and ask for the next page only while `last` is "
    "false. Every call spends from one budget of two requests per second. "
    "This is a reading task: change nothing in the books, even where a fix "
    "looks obvious, and name every gap in the data rather than filling it "
    "with a guess. Give no tax advice."
)


class Prompt(ABC):
    """One recipe a client offers a person.

    ``render`` returns the text of the one user message the client sends. It
    asks Lexware nothing and writes no log line. Every argument is a string,
    as MCP prompt arguments are, and an optional one defaults to the empty
    string, which the text says how to read.
    """

    #: The name a client calls the prompt by, and the name of its module.
    name: ClassVar[str]
    #: What a client shows a person in place of the name.
    title: ClassVar[str]

    @abstractmethod
    def render(self, *args: Any, **kwargs: Any) -> str:
        """The message, with the arguments filled in."""

    def register(self, server: MCPServer) -> None:
        """Add this prompt to ``server``, described by the docstring of ``render``."""
        server.prompt(name=self.name, title=self.title)(self.render)
