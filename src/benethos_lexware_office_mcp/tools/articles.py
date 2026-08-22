"""Articles: the catalogue a document's line items can be drawn from.

An article is a product or a service with a price, a unit and optionally a
number and a GTIN. Nothing about it is booked - it is master data of the
account's own making, which is why it is the one resource here that can be
deleted outright.

Two measurements from 2026-08-21 shape this module more than anything else.
The list endpoint filters on **three fields only**, and an unknown parameter
is ignored rather than refused, so a tool offering a text search would return
the whole catalogue while looking like it had searched. And a delete really
deletes: the record is gone, not archived, which is why `delete_article` asks
for a confirmation the other write tools do not.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .. import formatting
from ..client import ClientProvider
from ..config import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Settings
from ..errors import ConflictError, ValidationError
from ..payloads import ArticleType, article_body
from ..policy import classify
from ._base import PageNumber, register_tool

__all__ = ["register"]

ArticleId = Annotated[
    str,
    Field(description="The article's Lexware id, as returned by search_articles."),
]

# The API spells these in capitals and answers in capitals, so they are passed
# through as they are: a type read off a result can be sent straight back.
ArticleTypeField = Annotated[
    ArticleType | None,
    Field(description="Restrict to goods or to services. Left unset, both come back."),
]

# Every other list endpoint takes a page of one row. This one refuses
# anything below 25 with `size: MIN`, measured 2026-08-21 by the live check,
# so the floor is in the schema rather than in a failed request.
ArticlePageSize = Annotated[
    int,
    Field(
        description=(
            "Rows per page. The API refuses fewer than 25 here, unlike every "
            "other list."
        ),
        ge=DEFAULT_PAGE_SIZE,
        le=MAX_PAGE_SIZE,
    ),
]

LeadingPriceField = Annotated[
    Literal["NET", "GROSS"],
    Field(
        description=(
            "Whether `price` is before or after tax. The other figure is "
            "computed by the API from `tax_rate`."
        )
    ),
]


def register(server: MCPServer, settings: Settings, provider: ClientProvider) -> None:
    """Register the article tools. The policy file decides the rest."""

    @classify("read", "articles")
    async def search_articles(
        article_number: Annotated[
            str | None,
            Field(
                description=(
                    "The article number, matched in full. A fragment finds "
                    "nothing rather than everything starting with it."
                )
            ),
        ] = None,
        gtin: Annotated[
            str | None,
            Field(description="The barcode number, matched in full."),
        ] = None,
        article_type: ArticleTypeField = None,
        page: PageNumber = 0,
        size: ArticlePageSize = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """List articles, filtered by number, barcode or kind.

        One API call, one page. Rows carry the id, title, number, type, unit
        and price.

        **There is no search by title.** The API filters on these three fields
        and silently ignores anything else, so finding an article by name
        means paging through the list and reading the titles.

        Both filters match in full, not by fragment.
        """
        payload = await provider.get().articles(
            article_number=article_number,
            gtin=gtin,
            article_type=article_type,
            page=page,
            size=size,
        )
        return formatting.articles_page(payload)

    @classify("read", "articles")
    async def get_article(article_id: ArticleId) -> dict[str, Any]:
        """Read one article in full, by id.

        One API call. Returns the title, description, note, unit, type, the
        price block and the `version` an update has to send back.

        The price carries a net and a gross figure with the tax rate between
        them. `leadingPrice` says which of the two was entered and which the
        API computed.
        """
        return formatting.article(await provider.get().article(article_id))

    @classify("write", "articles", "create")
    async def create_article(
        title: Annotated[
            str,
            Field(
                description="What the article is called on a document.", min_length=1
            ),
        ],
        article_type: Annotated[
            ArticleType,
            Field(description="Whether this is goods or a service."),
        ],
        unit_name: Annotated[
            str,
            Field(
                description="What one of it is, for example 'Stueck' or 'Stunde'.",
                min_length=1,
            ),
        ],
        price: Annotated[
            float,
            Field(description="The price for one unit.", ge=0),
        ],
        tax_rate: Annotated[
            float,
            Field(description="The tax rate as a percentage, for example 19.", ge=0),
        ],
        leading_price: LeadingPriceField = "NET",
        article_number: Annotated[
            str | None,
            Field(description="Your own number for it. Not assigned by Lexware."),
        ] = None,
        gtin: Annotated[
            str | None,
            Field(description="Barcode number. Thirteen digits, checked by the API."),
        ] = None,
        description: Annotated[
            str | None,
            Field(description="Longer text shown under the title on a document."),
        ] = None,
        note: Annotated[
            str | None,
            Field(description="Internal note. Not shown on a document."),
        ] = None,
    ) -> dict[str, Any]:
        """Add an article to the catalogue.

        Writes to the account. One API call, and it is not retried.

        Returns the new id and `version`, not the record. Read it back with
        `get_article` to see the price the API computed from the one given.

        Unlike a voucher, an article can be removed again with
        `delete_article`.
        """
        body = article_body(
            title=title,
            article_type=article_type,
            unit_name=unit_name,
            price=price,
            leading_price=leading_price,
            tax_rate=tax_rate,
            article_number=article_number,
            gtin=gtin,
            description=description,
            note=note,
        )
        return dict(formatting.compact(await provider.get().create_article(body)))

    @classify("write", "articles", "update")
    async def update_article(
        article_id: ArticleId,
        version: Annotated[
            int,
            Field(
                description=(
                    "The `version` from the article as you last read it. If "
                    "the record has changed since, the update is refused "
                    "instead of overwriting that change."
                ),
                ge=0,
            ),
        ],
        title: Annotated[
            str | None, Field(description="New title.", min_length=1)
        ] = None,
        article_type: Annotated[
            ArticleType | None, Field(description="Change goods to service or back.")
        ] = None,
        unit_name: Annotated[
            str | None, Field(description="New unit.", min_length=1)
        ] = None,
        price: Annotated[
            float | None,
            Field(description="New price for one unit.", ge=0),
        ] = None,
        tax_rate: Annotated[
            float | None,
            Field(description="New tax rate as a percentage.", ge=0),
        ] = None,
        leading_price: Annotated[
            Literal["NET", "GROSS"] | None,
            Field(
                description=(
                    "Whether the new price is before or after tax. Left unset, "
                    "the side the article already used is kept."
                )
            ),
        ] = None,
        article_number: Annotated[
            str | None, Field(description="New article number.")
        ] = None,
        gtin: Annotated[str | None, Field(description="New barcode number.")] = None,
        description: Annotated[
            str | None, Field(description="New description.")
        ] = None,
        note: Annotated[str | None, Field(description="New internal note.")] = None,
    ) -> dict[str, Any]:
        """Change an article. Only the fields you give are changed.

        Read it with `get_article` first: that shows what is there and carries
        the `version` this needs. Two API calls.

        If the article changed since that read, nothing is written and the
        error says so.

        Giving `price` replaces the side named by `leading_price` and leaves
        the other for the API to recompute.
        """
        client = provider.get()
        current = await client.article(article_id)
        if current.get("version") != version:
            raise ConflictError(
                f"This article is at version {current.get('version')}, but the "
                f"update was written against version {version}. Somebody "
                "changed it in between. Read it again with get_article, check "
                "whether your change still applies, then retry."
            )

        body = article_body(
            base=current,
            title=title,
            article_type=article_type,
            unit_name=unit_name,
            price=price,
            leading_price=leading_price,
            tax_rate=tax_rate,
            article_number=article_number,
            gtin=gtin,
            description=description,
            note=note,
        )
        return dict(formatting.compact(await client.update_article(article_id, body)))

    @classify("write", "articles", "delete")
    async def delete_article(
        article_id: ArticleId,
        confirm: Annotated[
            bool,
            Field(
                description=(
                    "Must be true. Nothing is sent without it, so a call made "
                    "by accident fails instead of deleting something."
                )
            ),
        ] = False,
    ) -> dict[str, Any]:
        """Delete an article. The API has no way back.

        The record is removed, not archived: reading it afterwards is a "not
        found". One API call, and only once `confirm` is true.

        Documents that already quote this article keep their line items, which
        hold their own copy of the text and the price.
        """
        if not confirm:
            raise ValidationError(
                "delete_article removes the record and the API cannot bring "
                "it back. Pass confirm=true once you are sure, or read it "
                "first with get_article."
            )
        await provider.get().delete_article(article_id)
        return {"deleted": article_id}

    register_tool(server, search_articles)
    register_tool(server, get_article)
    register_tool(server, create_article)
    register_tool(server, update_article)
    register_tool(server, delete_article)
