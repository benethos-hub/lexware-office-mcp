"""The four configured lists, and the trimming that makes them answerable.

The fixtures are the shapes the live API returned on 2026-08-21, with the ids
replaced. Two things measured that day drive most of the assertions: these
endpoints answer with a **bare list** rather than the page envelope every
other list endpoint uses, and two of them are long — 257 countries and 231
posting categories — so an untrimmed answer would be tens of thousands of
characters.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp import formatting
from benethos_lexware_office_mcp.client import ClientProvider, LexwareClient
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.errors import UpstreamError
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import build_server
from benethos_lexware_office_mcp.tools.master_data import KINDS

API_KEY = "test-key-0123456789"

COUNTRIES: list[dict[str, Any]] = [
    {
        "countryCode": "DE",
        "countryNameEN": "Germany",
        "countryNameDE": "Deutschland",
        "taxClassification": "de",
    },
    {
        "countryCode": "AT",
        "countryNameEN": "Austria",
        "countryNameDE": "Oesterreich",
        "taxClassification": "intraCommunity",
    },
    {
        "countryCode": "AF",
        "countryNameEN": "Afghanistan",
        "countryNameDE": "Afghanistan",
        "taxClassification": "thirdPartyCountry",
    },
]

CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "PLACEHOLDER-CATEGORY-1",
        "name": "Dienstleistung",
        "groupName": "Einnahmen",
        "type": "income",
        "contactRequired": False,
        "splitAllowed": True,
    },
    {
        "id": "PLACEHOLDER-CATEGORY-2",
        "name": "Wareneinkauf",
        "groupName": "Material/Waren",
        "type": "outgo",
        "contactRequired": False,
        "splitAllowed": True,
    },
    {
        "id": "PLACEHOLDER-CATEGORY-3",
        "name": "Privatentnahme",
        "groupName": "Privat",
        "type": "outgo",
        "contactRequired": True,
        "splitAllowed": False,
    },
]

LAYOUTS: list[dict[str, Any]] = [
    {"id": "PLACEHOLDER-LAYOUT-1", "name": "Standard", "default": True}
]


async def _no_sleep(_seconds: float) -> None:
    return None


class Scripted:
    """Answers a scripted sequence, and remembers what it was asked for."""

    def __init__(self, *responses: tuple[int, Any]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, payload = self._responses.pop(0) if self._responses else (200, [])
        return httpx.Response(status, json=payload)

    @property
    def path(self) -> str:
        return urlparse(str(self.requests[-1].url)).path


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


async def test_the_list_is_read_from_the_path_the_kind_names() -> None:
    handler = Scripted((200, CATEGORIES))
    async with make_client(handler) as client:
        entries = await client.master_data("posting-categories")

    assert handler.path == "/v1/posting-categories"
    assert len(handler.requests) == 1, "one API call, as the description says"
    assert entries == CATEGORIES


async def test_an_envelope_where_a_list_was_promised_is_refused() -> None:
    """These four do not page. A page envelope would mean the API changed."""
    handler = Scripted((200, {"content": CATEGORIES, "totalPages": 1}))
    async with make_client(handler) as client:
        with pytest.raises(UpstreamError):
            await client.master_data("posting-categories")


# -- formatting -----------------------------------------------------------


def test_the_answer_says_what_it_left_out() -> None:
    result = formatting.master_data("countries", COUNTRIES, limit=2)

    assert result["total"] == 3
    assert result["shown"] == 2
    assert len(result["entries"]) == 2


def test_matched_appears_only_when_something_was_searched_for() -> None:
    """Without a search it would only restate `total`."""
    assert "matched" not in formatting.master_data("countries", COUNTRIES, limit=25)

    searched = formatting.master_data(
        "countries", COUNTRIES, search="Deutschland", limit=25
    )
    assert searched["matched"] == 1
    assert searched["total"] == 3


def test_the_search_reads_every_text_a_row_carries() -> None:
    """One parameter instead of one per field: name, group, code and type."""
    by_type = formatting.master_data(
        "posting-categories", CATEGORIES, search="outgo", limit=25
    )
    by_group = formatting.master_data(
        "posting-categories", CATEGORIES, search="Material", limit=25
    )
    by_code = formatting.master_data("countries", COUNTRIES, search="AT", limit=25)

    assert [row["name"] for row in by_type["entries"]] == [
        "Wareneinkauf",
        "Privatentnahme",
    ]
    assert [row["name"] for row in by_group["entries"]] == ["Wareneinkauf"]
    assert [row["countryCode"] for row in by_code["entries"]] == ["AT"]


def test_the_search_ignores_case() -> None:
    result = formatting.master_data(
        "posting-categories", CATEGORIES, search="WARENEINKAUF", limit=25
    )

    assert result["matched"] == 1


def test_an_id_is_not_searchable_text() -> None:
    """A UUID matches a search term only by accident, never on purpose."""
    result = formatting.master_data(
        "posting-categories", CATEGORIES, search="PLACEHOLDER", limit=25
    )

    assert result["matched"] == 0
    assert result["entries"] == []


def test_a_search_that_finds_nothing_still_answers_in_the_same_shape() -> None:
    result = formatting.master_data("countries", COUNTRIES, search="zzz", limit=25)

    assert result["entries"] == [], "an empty list, not a missing key"
    assert result["shown"] == 0
    assert result["total"] == 3


def test_nothing_is_dropped_from_a_row() -> None:
    """Every field of these four kinds carries a decision, `false` included."""
    result = formatting.master_data(
        "posting-categories", CATEGORIES, search="Privatentnahme", limit=25
    )
    row = result["entries"][0]

    assert row == CATEGORIES[2]
    assert row["contactRequired"] is True
    assert row["splitAllowed"] is False


def test_a_row_that_is_not_an_object_is_skipped() -> None:
    result = formatting.master_data("print-layouts", [*LAYOUTS, "nonsense"], limit=25)

    assert result["total"] == 1


# -- the tool -------------------------------------------------------------


@pytest.mark.parametrize(("kind", "segment"), sorted(KINDS.items()))
async def test_every_kind_reaches_its_own_path(kind: str, segment: str) -> None:
    handler = Scripted((200, LAYOUTS))
    server, provider = server_for(handler)

    await server.call_tool("get_master_data", {"kind": kind})

    assert handler.path == f"/v1/{segment}"
    await provider.aclose()


async def test_the_categories_come_back_with_their_ids() -> None:
    """The id is what `create_voucher` books against."""
    handler = Scripted((200, CATEGORIES))
    server, provider = server_for(handler)

    result = await server.call_tool(
        "get_master_data", {"kind": "posting-categories", "search": "Dienstleistung"}
    )

    assert result.structured_content is not None
    entries = result.structured_content["entries"]
    assert entries[0]["id"] == "PLACEHOLDER-CATEGORY-1"
    assert entries[0]["type"] == "income"
    await provider.aclose()


async def test_the_default_answer_is_capped() -> None:
    handler = Scripted((200, COUNTRIES * 200))
    server, provider = server_for(handler)

    result = await server.call_tool("get_master_data", {"kind": "countries"})

    assert result.structured_content is not None
    assert result.structured_content["total"] == 600
    assert result.structured_content["shown"] == 25, "the default page size"
    await provider.aclose()


@pytest.mark.parametrize("limit", [0, 251])
async def test_a_limit_outside_the_bounds_never_reaches_the_api(limit: int) -> None:
    handler = Scripted((200, COUNTRIES))
    server, provider = server_for(handler)

    with pytest.raises(ToolError):
        await server.call_tool("get_master_data", {"kind": "countries", "limit": limit})

    assert handler.requests == []
    await provider.aclose()


async def test_an_unknown_kind_never_reaches_the_api() -> None:
    handler = Scripted((200, COUNTRIES))
    server, provider = server_for(handler)

    with pytest.raises(ToolError):
        await server.call_tool("get_master_data", {"kind": "articles"})

    assert handler.requests == []
    await provider.aclose()


async def test_the_kinds_are_the_ones_the_client_is_offered() -> None:
    handler = Scripted()
    server, provider = server_for(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    offered = tools["get_master_data"].input_schema["properties"]["kind"]

    assert set(offered["enum"]) == set(KINDS)
    await provider.aclose()


async def test_the_description_says_what_it_costs_and_to_narrow_the_search() -> None:
    handler = Scripted()
    server, provider = server_for(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    description = tools["get_master_data"].description or ""

    assert "one api call" in description.lower()
    assert "search" in description.lower()
    assert len(description) < 700, "the description budget, see CLAUDE.md"
    await provider.aclose()
