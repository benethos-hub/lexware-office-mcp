"""The catalogue: five tools, three filters that work, and one deletion.

The fixtures are the shapes the live API returned on 2026-08-21, with the ids
replaced. Three measurements from that day are what most of these assertions
protect:

- the list endpoint filters on `articleNumber`, `gtin` and `type` and
  **ignores** anything else, so a text search would have looked like it
  worked while returning the whole catalogue,
- a price is one number and a side, and the API computes the other,
- a delete is a real delete: 204, then 404 on the same id.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp import formatting
from benethos_lexware_office_mcp.client import ClientProvider, LexwareClient
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.payloads import article_body
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import build_server

API_KEY = "test-key-0123456789"

ARTICLE: dict[str, Any] = {
    "id": "PLACEHOLDER-ARTICLE-1",
    "organizationId": "PLACEHOLDER-ORG-ID",
    "createdDate": "2026-08-21T17:34:35.574+02:00",
    "updatedDate": "2026-08-21T17:34:35.583+02:00",
    "archived": False,
    "title": "Probe Artikel",
    "description": "a longer text shown on the document",
    "type": "PRODUCT",
    "articleNumber": "A-0001",
    "gtin": "4012345678901",
    "note": "internal",
    "unitName": "Stueck",
    "price": {
        "leadingPrice": "NET",
        "netPrice": 100.0,
        "grossPrice": 119.0,
        "taxRate": 19,
    },
    "version": 0,
}

PAGE: dict[str, Any] = {
    "content": [ARTICLE],
    "first": True,
    "last": True,
    "number": 0,
    "numberOfElements": 1,
    "size": 25,
    "sort": [{"property": "title", "nullHandling": "NATIVE"}],
    "totalElements": 1,
    "totalPages": 1,
}

WRITTEN: dict[str, Any] = {
    "id": "PLACEHOLDER-ARTICLE-1",
    "resourceUri": "https://api.lexware.io/v1/articles/PLACEHOLDER-ARTICLE-1",
    "createdDate": "2026-08-21T17:34:35.574+02:00",
    "updatedDate": "2026-08-21T17:34:35.583+02:00",
    "version": 0,
}


async def _no_sleep(_seconds: float) -> None:
    return None


class Scripted:
    """Answers a scripted sequence, and remembers what it was sent."""

    def __init__(self, *responses: tuple[int, Any]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, payload = self._responses.pop(0) if self._responses else (200, {})
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json=payload)

    @property
    def methods(self) -> list[str]:
        return [request.method for request in self.requests]

    @property
    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(str(self.requests[-1].url)).query)

    @property
    def path(self) -> str:
        return urlparse(str(self.requests[-1].url)).path

    def body(self, index: int) -> Any:
        return json.loads(self.requests[index].content)


def make_client(handler: Scripted) -> LexwareClient:
    return LexwareClient(
        Settings(api_key=API_KEY),
        transport=httpx.MockTransport(handler),
        bucket=TokenBucket(1000.0, 100, sleep=_no_sleep),
        sleep=_no_sleep,
    )


def server_for(handler: Scripted) -> tuple[Any, ClientProvider]:
    settings = Settings(api_key=API_KEY)
    provider = ClientProvider(
        settings,
        transport=httpx.MockTransport(handler),
        bucket=TokenBucket(1000.0, 100, sleep=_no_sleep),
        sleep=_no_sleep,
    )
    return build_server(settings, provider), provider


# -- client ---------------------------------------------------------------


async def test_only_the_three_filters_that_work_are_sent() -> None:
    """An unknown parameter is ignored upstream, so sending one is worse than
    useless: it looks like a filter and answers with everything."""
    handler = Scripted((200, PAGE))
    async with make_client(handler) as client:
        await client.articles(
            article_number="A-0001",
            gtin="4012345678901",
            article_type="PRODUCT",
            page=2,
            size=10,
        )

    query = handler.query
    assert query["articleNumber"] == ["A-0001"]
    assert query["gtin"] == ["4012345678901"]
    assert query["type"] == ["PRODUCT"]
    assert query["page"] == ["2"]
    assert query["size"] == ["10"]
    assert set(query) == {"articleNumber", "gtin", "type", "page", "size"}


async def test_an_unset_filter_is_left_out_entirely() -> None:
    handler = Scripted((200, PAGE))
    async with make_client(handler) as client:
        await client.articles()

    assert set(handler.query) == {"page", "size"}


async def test_a_delete_sends_nothing_and_expects_nothing_back() -> None:
    """Verified 2026-08-21: 204 with an empty body."""
    handler = Scripted((204, None))
    async with make_client(handler) as client:
        assert await client.delete_article("PLACEHOLDER-ARTICLE-1") is None

    assert handler.methods == ["DELETE"]
    assert handler.path == "/v1/articles/PLACEHOLDER-ARTICLE-1"


# -- the request body -----------------------------------------------------


def test_a_new_article_carries_the_price_on_the_side_that_was_named() -> None:
    body = article_body(
        title="T",
        article_type="SERVICE",
        unit_name="Stunde",
        price=90.0,
        leading_price="NET",
        tax_rate=19,
    )

    assert body["price"] == {"leadingPrice": "NET", "netPrice": 90.0, "taxRate": 19}
    assert "grossPrice" not in body["price"], "the API computes the other side"
    assert body["version"] == 0


def test_a_gross_price_lands_in_the_gross_field() -> None:
    body = article_body(
        title="T",
        article_type="PRODUCT",
        unit_name="St",
        price=11.9,
        leading_price="GROSS",
        tax_rate=19,
    )

    assert body["price"]["grossPrice"] == 11.9
    assert "netPrice" not in body["price"]


def test_an_update_starts_from_the_record_and_keeps_what_was_not_named() -> None:
    """A PUT replaces rather than patches, so the rest has to come along."""
    body = article_body(base=ARTICLE, title="New title")

    assert body["title"] == "New title"
    assert body["note"] == "internal"
    assert body["gtin"] == "4012345678901"
    assert body["version"] == 0


def test_an_update_drops_what_the_record_only_reports() -> None:
    body = article_body(base=ARTICLE, title="New title")

    for key in ("id", "organizationId", "createdDate", "updatedDate"):
        assert key not in body


def test_a_new_price_replaces_the_stale_other_side() -> None:
    """The read-back record carries both figures. Sending the old gross price
    beside a new net one would be a number contradicting itself."""
    body = article_body(base=ARTICLE, price=200.0)

    assert body["price"]["netPrice"] == 200.0
    assert "grossPrice" not in body["price"]
    assert body["price"]["leadingPrice"] == "NET"
    assert body["price"]["taxRate"] == 19


def test_changing_the_side_moves_the_price_across() -> None:
    body = article_body(base=ARTICLE, price=238.0, leading_price="GROSS")

    assert body["price"] == {
        "leadingPrice": "GROSS",
        "grossPrice": 238.0,
        "taxRate": 19,
    }


def test_an_update_that_touches_no_price_leaves_it_exactly_as_it_was() -> None:
    body = article_body(base=ARTICLE, note="changed")

    assert body["price"] == ARTICLE["price"]


# -- formatting -----------------------------------------------------------


def test_a_row_leaves_out_what_only_a_full_read_needs() -> None:
    row = formatting.article_row(ARTICLE)

    assert row["title"] == "Probe Artikel"
    assert row["price"]["netPrice"] == 100.0
    for key in ("description", "note", "organizationId", "createdDate"):
        assert key not in row


def test_a_row_hides_archived_unless_it_is_true() -> None:
    assert "archived" not in formatting.article_row(ARTICLE)
    assert formatting.article_row({**ARTICLE, "archived": True})["archived"] is True


def test_a_full_article_keeps_everything_but_the_organization() -> None:
    full = formatting.article(ARTICLE)

    assert full["description"] == "a longer text shown on the document"
    assert full["price"] == ARTICLE["price"]
    assert full["version"] == 0
    assert "organizationId" not in full


def test_a_field_this_project_has_never_seen_still_arrives() -> None:
    full = formatting.article({**ARTICLE, "invented": "kept"})

    assert full["invented"] == "kept"


# -- the tools ------------------------------------------------------------


async def test_the_search_answers_in_the_shared_page_shape() -> None:
    handler = Scripted((200, PAGE))
    server, provider = server_for(handler)

    result = await server.call_tool("search_articles", {"article_type": "SERVICE"})

    assert result.structured_content is not None
    assert result.structured_content["page"]["totalElements"] == 1
    assert result.structured_content["articles"][0]["articleNumber"] == "A-0001"
    assert handler.query["type"] == ["SERVICE"]
    await provider.aclose()


async def test_reading_one_returns_it_whole() -> None:
    handler = Scripted((200, ARTICLE))
    server, provider = server_for(handler)

    result = await server.call_tool(
        "get_article", {"article_id": "PLACEHOLDER-ARTICLE-1"}
    )

    assert result.structured_content is not None
    assert result.structured_content["unitName"] == "Stueck"
    await provider.aclose()


async def test_creating_one_sends_the_four_fields_the_api_insists_on() -> None:
    """Measured 2026-08-21: title, type, unitName and price, or a 406 naming
    each one it did not get."""
    handler = Scripted((201, WRITTEN))
    server, provider = server_for(handler)

    await server.call_tool(
        "create_article",
        {
            "title": "Beratung",
            "article_type": "SERVICE",
            "unit_name": "Stunde",
            "price": 90.0,
            "tax_rate": 19,
        },
    )

    body = handler.body(0)
    assert handler.methods == ["POST"]
    assert body["title"] == "Beratung"
    assert body["type"] == "SERVICE"
    assert body["unitName"] == "Stunde"
    assert body["price"] == {"leadingPrice": "NET", "netPrice": 90.0, "taxRate": 19}
    await provider.aclose()


async def test_an_update_reads_first_and_then_replaces() -> None:
    handler = Scripted((200, ARTICLE), (200, {**ARTICLE, "version": 1}))
    server, provider = server_for(handler)

    await server.call_tool(
        "update_article",
        {"article_id": "PLACEHOLDER-ARTICLE-1", "version": 0, "title": "Renamed"},
    )

    assert handler.methods == ["GET", "PUT"]
    assert handler.body(1)["title"] == "Renamed"
    assert handler.body(1)["unitName"] == "Stueck", "the rest came along"
    await provider.aclose()


async def test_a_stale_version_is_refused_before_anything_is_sent() -> None:
    handler = Scripted((200, {**ARTICLE, "version": 3}))
    server, provider = server_for(handler)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(
            "update_article",
            {"article_id": "PLACEHOLDER-ARTICLE-1", "version": 0, "title": "Renamed"},
        )

    assert "version 3" in str(excinfo.value)
    assert handler.methods == ["GET"], "no write went out"
    await provider.aclose()


async def test_a_delete_without_a_confirmation_never_reaches_the_api() -> None:
    handler = Scripted((204, None))
    server, provider = server_for(handler)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(
            "delete_article", {"article_id": "PLACEHOLDER-ARTICLE-1"}
        )

    assert "confirm" in str(excinfo.value)
    assert handler.requests == [], "a request went out anyway"
    await provider.aclose()


async def test_a_confirmed_delete_goes_through_and_says_what_it_removed() -> None:
    handler = Scripted((204, None))
    server, provider = server_for(handler)

    result = await server.call_tool(
        "delete_article",
        {"article_id": "PLACEHOLDER-ARTICLE-1", "confirm": True},
    )

    assert handler.methods == ["DELETE"]
    assert result.structured_content == {"deleted": "PLACEHOLDER-ARTICLE-1"}
    await provider.aclose()


async def test_a_page_smaller_than_the_api_allows_never_leaves_the_server() -> None:
    """Measured 2026-08-21 by the live check in `tests/smoke.py`, on its first
    run: this endpoint refuses `size` below 25 with `size: MIN`, where every
    other list takes a page of one. The floor is in the schema, so a caller
    reading it never writes the call that fails."""
    handler = Scripted((200, PAGE))
    server, provider = server_for(handler)

    with pytest.raises(ToolError):
        await server.call_tool("search_articles", {"size": 5})

    assert handler.requests == []
    await provider.aclose()


async def test_the_page_floor_is_in_the_schema_the_client_reads() -> None:
    handler = Scripted()
    server, provider = server_for(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    size = tools["search_articles"].input_schema["properties"]["size"]

    assert size["minimum"] == 25
    assert size["maximum"] == 250
    await provider.aclose()


async def test_the_search_offers_no_parameter_that_looks_like_a_text_search() -> None:
    """The whole point of the measurement: `query` and `title` are ignored
    upstream, so offering either would be a lie in the schema."""
    handler = Scripted()
    server, provider = server_for(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    offered = set(tools["search_articles"].input_schema["properties"])

    assert offered == {"article_number", "gtin", "article_type", "page", "size"}
    await provider.aclose()


async def test_the_deleting_tool_says_the_api_has_no_way_back() -> None:
    """It says that rather than "cannot be undone": this server speaks for the
    interface it uses, and the web app is a different question. See SPECS
    section 5."""
    handler = Scripted()
    server, provider = server_for(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    description = tools["delete_article"].description or ""

    assert "no way back" in description.lower()
    assert "confirm" in description.lower()
    assert len(description) < 700, "the description budget, see CLAUDE.md"
    await provider.aclose()
