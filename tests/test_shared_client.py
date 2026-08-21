"""One client, one bucket, per server process.

Golden rule 5 says every outbound request passes *the* shared token bucket.
The first version of the profile tool built its own client per call, so each
call got a full bucket of its own — ten calls would have been ten limiters,
each one convinced it was within a limit the account had already blown. These
tests exist so that cannot come back.
"""

from __future__ import annotations

import httpx

from benethos_lexware_office_mcp.client import ClientProvider
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import build_server

PROFILE = {"organizationId": "PLACEHOLDER", "companyName": "Example GmbH"}


async def _no_sleep(_seconds: float) -> None:
    return None


def offline_provider(settings: Settings) -> ClientProvider:
    return ClientProvider(
        settings,
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=PROFILE)),
        bucket=TokenBucket(1000.0, 100, sleep=_no_sleep),
        sleep=_no_sleep,
    )


def test_the_provider_hands_out_the_same_client_every_time() -> None:
    provider = ClientProvider(Settings(api_key="k" * 20))
    assert provider.get() is provider.get()


def test_the_client_is_not_built_until_it_is_used() -> None:
    """Listing tools must not open a connection pool nobody asked for."""
    provider = ClientProvider(Settings(api_key="k" * 20))
    assert provider._client is None
    provider.get()
    assert provider._client is not None


async def test_repeated_tool_calls_share_one_bucket() -> None:
    """The regression this module exists for."""
    acquisitions: list[int] = []

    class CountingBucket(TokenBucket):
        async def acquire(self, tokens: int = 1) -> None:
            acquisitions.append(id(self))

    settings = Settings(api_key="k" * 20)
    provider = ClientProvider(
        settings,
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=PROFILE)),
        bucket=CountingBucket(1000.0, 100),
        sleep=_no_sleep,
    )
    server = build_server(settings, provider)

    for _ in range(3):
        await server.call_tool("get_profile", {})

    assert len(acquisitions) == 3
    assert len(set(acquisitions)) == 1, "each call used a bucket of its own"
    await provider.aclose()


async def test_closing_the_provider_releases_the_client() -> None:
    provider = offline_provider(Settings(api_key="k" * 20))
    provider.get()
    await provider.aclose()
    assert provider._client is None
