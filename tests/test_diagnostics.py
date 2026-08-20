"""The first tool, end to end: registration, description, and one call."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from benethos_lexware_office_mcp import client as client_module
from benethos_lexware_office_mcp import policy
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import build_server

PROFILE = {
    "organizationId": "PLACEHOLDER-ORG-ID",
    "companyName": "Example GmbH",
    "taxType": "net",
    "smallBusiness": False,
    "distanceSalesPrincipal": None,
}


@pytest.fixture(autouse=True)
def _restore_mode() -> Iterator[None]:
    previous = policy.active_mode()
    yield
    policy.set_active_mode(previous)


@pytest.fixture
def offline_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every client this test builds at a mock transport."""
    original = client_module.LexwareClient.__init__

    async def no_sleep(_seconds: float) -> None:
        return None

    def patched(self, settings, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault(
            "transport",
            httpx.MockTransport(lambda request: httpx.Response(200, json=PROFILE)),
        )
        kwargs.setdefault("bucket", TokenBucket(1000.0, 100, sleep=no_sleep))
        kwargs.setdefault("sleep", no_sleep)
        original(self, settings, **kwargs)

    monkeypatch.setattr(client_module.LexwareClient, "__init__", patched)


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


async def test_get_profile_returns_the_account(offline_api: None) -> None:
    server = build_server(Settings(api_key="test-key-0123456789"))
    result = await server.call_tool("get_profile", {})
    assert result.is_error is not True
    payload = result.structured_content
    assert payload is not None
    assert payload["companyName"] == "Example GmbH"
    assert payload["smallBusiness"] is False
    # Compacted away rather than reported as null.
    assert "distanceSalesPrincipal" not in payload


async def test_get_profile_is_still_available_in_full_mode() -> None:
    """A read tool must not disappear when the tier is raised."""
    server = build_server(Settings(mode="full"))
    names = [tool.name for tool in await server.list_tools()]
    assert "get_profile" in names


async def test_the_description_carries_no_source_indentation() -> None:
    """Descriptions are sent on every request, so the whitespace is not free."""
    server = build_server(Settings())
    tool = next(t for t in await server.list_tools() if t.name == "get_profile")
    assert tool.description is not None
    assert not any(line.startswith(" ") for line in tool.description.splitlines())
    assert tool.description == tool.description.strip()
