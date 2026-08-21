"""The lists an account is configured with, rather than records in it.

Countries, payment conditions, posting categories and print layouts have
nothing in common except how they are used: something else needs an id or a
code from them before it can be written. They are therefore one tool with a
`kind` rather than four, which is what section 8 of SPECS.md asks for wherever
endpoints differ only in their path.

Two of the four are long - 257 countries and 231 posting categories in a live
account - and none of them pages, so the trimming that keeps an answer small
happens after the call rather than in it. See
:func:`..formatting.master_data`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .. import formatting
from ..client import ClientProvider
from ..config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Settings
from ..policy import classify
from ._base import register_tool

__all__ = ["KINDS", "MasterDataKind", "register"]

# The path segment is the kind, for all four. Written out anyway, so that no
# part of a URL is ever assembled from a string that was not checked first.
MasterDataKind = Literal[
    "countries",
    "payment-conditions",
    "posting-categories",
    "print-layouts",
]

KINDS: dict[str, str] = {
    "countries": "countries",
    "payment-conditions": "payment-conditions",
    "posting-categories": "posting-categories",
    "print-layouts": "print-layouts",
}


def register(server: MCPServer, settings: Settings, provider: ClientProvider) -> None:
    """Register the master data tool. The policy file decides the rest."""

    @classify("read", "master_data")
    async def get_master_data(
        kind: Annotated[
            MasterDataKind,
            Field(
                description=(
                    "Which list to read. 'posting-categories' holds the "
                    "categories a bookkeeping voucher books against, "
                    "'countries' the codes an address takes."
                )
            ),
        ],
        search: Annotated[
            str | None,
            Field(
                description=(
                    "Narrow the list. Matched case-insensitively against "
                    "every text a row carries, so 'income' keeps the "
                    "categories of that type and 'Erloese' those named so."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                description="How many rows to put in the answer.",
                ge=1,
                le=MAX_PAGE_SIZE,
            ),
        ] = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """Read one of the lists this account is configured with.

        One API call. Countries and posting categories run into the hundreds,
        so `search` is usually the difference between an answer and a wall of
        rows.

        The answer reports `total`, what the account holds, and `shown`, what
        is in it. When those differ, narrow the search rather than raising
        `limit`.

        A posting category id is what `create_voucher` books against, and
        `type` says whether a category takes money in or out.
        """
        entries = await provider.get().master_data(KINDS[kind])
        return formatting.master_data(kind, entries, search=search, limit=limit)

    register_tool(server, get_master_data)
