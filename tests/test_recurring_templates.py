"""Templates that issue invoices on a schedule.

The one group in this server whose record shape has never been seen: the test
account holds no template and the API offers no way to create one, so the
fixture below is a shape taken from the documentation rather than from a
response. That is exactly why the formatting is a drop-list of one field -
anything narrower would be a guess - and why SPECS marks the shape
**(to verify)**. What *is* measured here is the envelope, the paging, and
which sort values the API accepts, all of which were sent on 2026-08-21.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp import formatting
from benethos_lexware_office_mcp.client import ClientProvider, LexwareClient
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import build_server

API_KEY = "test-key-0123456789"

TEMPLATE: dict[str, Any] = {
    "id": "PLACEHOLDER-TEMPLATE-1",
    "organizationId": "PLACEHOLDER-ORG-ID",
    "createdDate": "2026-08-01T10:00:00.000+02:00",
    "updatedDate": "2026-08-01T10:00:00.000+02:00",
    "version": 1,
    "address": {"contactId": "PLACEHOLDER-CONTACT-1", "name": "Testa Musterperson"},
    "lineItems": [],
    "totalPrice": {"currency": "EUR", "totalNetAmount": 100.0},
    "recurringTemplateSettings": {
        "id": "PLACEHOLDER-SETTINGS-1",
        "startDate": "2026-09-01",
        "nextExecutionDate": "2026-09-01",
        "lastExecutionFinishDate": None,
        "executionInterval": "MONTHLY",
        "finalize": True,
    },
}

PAGE: dict[str, Any] = {
    "content": [TEMPLATE],
    "first": True,
    "last": True,
    "number": 0,
    "numberOfElements": 1,
    "size": 25,
    "sort": [{"property": "updatedDate", "direction": "DESC"}],
    "totalElements": 1,
    "totalPages": 1,
}


async def _no_sleep(_seconds: float) -> None:
    return None


class Scripted:
    def __init__(self, *responses: tuple[int, Any]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, payload = self._responses.pop(0) if self._responses else (200, {})
        return httpx.Response(status, json=payload)

    @property
    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(str(self.requests[-1].url)).query)

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


async def test_the_page_is_asked_for_by_paging_alone() -> None:
    handler = Scripted((200, PAGE))
    async with make_client(handler) as client:
        await client.recurring_templates(page=1, size=50)

    assert handler.path == "/v1/recurring-templates"
    assert handler.query == {"page": ["1"], "size": ["50"]}


async def test_a_sort_is_passed_through_and_omitted_when_unset() -> None:
    handler = Scripted((200, PAGE), (200, PAGE))
    async with make_client(handler) as client:
        await client.recurring_templates(sort="nextExecutionDate,ASC")
        assert handler.query["sort"] == ["nextExecutionDate,ASC"]
        await client.recurring_templates()
        assert "sort" not in handler.query


async def test_one_template_is_read_from_its_own_path() -> None:
    handler = Scripted((200, TEMPLATE))
    async with make_client(handler) as client:
        await client.recurring_template("PLACEHOLDER-TEMPLATE-1")

    assert handler.path == "/v1/recurring-templates/PLACEHOLDER-TEMPLATE-1"


# -- formatting -----------------------------------------------------------


def test_only_the_organization_is_dropped() -> None:
    """A record this project has never seen keeps everything else it sends."""
    formatted = formatting.recurring_template(TEMPLATE)

    assert "organizationId" not in formatted
    assert formatted["recurringTemplateSettings"]["executionInterval"] == "MONTHLY"
    assert formatted["version"] == 1


def test_an_unseen_field_survives() -> None:
    formatted = formatting.recurring_template({**TEMPLATE, "invented": "kept"})

    assert formatted["invented"] == "kept"


def test_the_page_uses_the_shared_envelope() -> None:
    formatted = formatting.recurring_templates_page(PAGE)

    assert formatted["page"]["totalElements"] == 1
    assert formatted["templates"][0]["id"] == "PLACEHOLDER-TEMPLATE-1"


# -- the tool -------------------------------------------------------------


async def test_without_an_id_a_page_comes_back() -> None:
    handler = Scripted((200, PAGE))
    server, provider = server_for(handler)

    result = await server.call_tool("get_recurring_templates", {})

    assert result.structured_content is not None
    assert result.structured_content["page"]["totalElements"] == 1
    assert handler.path == "/v1/recurring-templates"
    await provider.aclose()


async def test_with_an_id_that_one_template_comes_back() -> None:
    handler = Scripted((200, TEMPLATE))
    server, provider = server_for(handler)

    result = await server.call_tool(
        "get_recurring_templates", {"template_id": "PLACEHOLDER-TEMPLATE-1"}
    )

    assert result.structured_content is not None
    assert result.structured_content["version"] == 1
    assert handler.path == "/v1/recurring-templates/PLACEHOLDER-TEMPLATE-1"
    await provider.aclose()


async def test_a_sort_the_api_refuses_never_leaves_the_server() -> None:
    """Measured 2026-08-21: `title` comes back as "must be one of" four dates,
    so the schema offers those four and nothing else."""
    handler = Scripted((200, PAGE))
    server, provider = server_for(handler)

    with pytest.raises(ToolError):
        await server.call_tool("get_recurring_templates", {"sort": "title,ASC"})

    assert handler.requests == []
    await provider.aclose()


async def test_the_description_says_reading_is_all_there_is() -> None:
    handler = Scripted()
    server, provider = server_for(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    description = tools["get_recurring_templates"].description or ""

    assert "one api call" in description.lower()
    assert len(description) < 700, "the description budget, see CLAUDE.md"
    await provider.aclose()
