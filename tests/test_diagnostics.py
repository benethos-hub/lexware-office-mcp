"""The first tool, end to end: registration, description, and one call."""

from __future__ import annotations

import httpx
import pytest

from benethos_lexware_office_mcp import client as client_module
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import build_server

# The shape confirmed against a live account on 2026-08-20, with placeholder
# identifiers. `created` is present because the API returns it and the tool has
# to be shown dropping it.
PROFILE = {
    "organizationId": "PLACEHOLDER-ORG-ID",
    "connectionId": "PLACEHOLDER-CONNECTION-ID",
    "companyName": "Example GmbH",
    "taxType": "net",
    "smallBusiness": False,
    "businessFeatures": ["INVOICING", "BOOKKEEPING"],
    "created": {
        "date": "2026-01-01T00:00:00.000Z",
        "userEmail": "someone@example.invalid",
        "userName": "someone@example.invalid",
    },
    "distanceSalesPrincipal": None,
}


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def offline_api() -> client_module.ClientProvider:
    """The one client the server may have, pointed at a mock transport."""
    return client_module.ClientProvider(
        Settings(api_key="test-key-0123456789"),
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=PROFILE)),
        bucket=TokenBucket(1000.0, 100, sleep=_no_sleep),
        sleep=_no_sleep,
    )


async def test_get_profile_is_listed_in_read_mode() -> None:
    server = build_server(Settings())
    names = [tool.name for tool in await server.list_tools()]
    assert "get_profile" in names


async def test_the_description_tells_the_model_when_to_use_it() -> None:
    """The docstring is what the model actually reads, so it is worth asserting."""
    server = build_server(Settings())
    tool = next(t for t in await server.list_tools() if t.name == "get_profile")
    assert tool.description is not None
    assert "connection check" in tool.description
    assert "one api call" in tool.description.lower()


async def test_get_profile_returns_the_account(
    offline_api: client_module.ClientProvider,
) -> None:
    server = build_server(Settings(api_key="test-key-0123456789"), offline_api)
    result = await server.call_tool("get_profile", {})
    assert result.is_error is not True
    payload = result.structured_content
    assert payload is not None
    assert payload["companyName"] == "Example GmbH"
    assert payload["smallBusiness"] is False
    # Compacted away rather than reported as null.
    assert "distanceSalesPrincipal" not in payload
    # The creating user's address never reaches the model.
    assert "example.invalid" not in str(payload)
    await offline_api.aclose()


async def test_get_profile_is_still_available_in_full_mode() -> None:
    """A read tool must not disappear when the tier is raised."""
    server = build_server(Settings())
    names = [tool.name for tool in await server.list_tools()]
    assert "get_profile" in names


async def test_the_description_carries_no_source_indentation() -> None:
    """Descriptions are sent on every request, so the whitespace is not free."""
    server = build_server(Settings())
    tool = next(t for t in await server.list_tools() if t.name == "get_profile")
    assert tool.description is not None
    assert not any(line.startswith(" ") for line in tool.description.splitlines())
    assert tool.description == tool.description.strip()
