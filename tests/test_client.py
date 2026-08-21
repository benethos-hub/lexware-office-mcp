"""The HTTP client: error mapping and the retry rules. Offline throughout."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from benethos_lexware_office_mcp.client import BREAKER_THRESHOLD, LexwareClient
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.errors import (
    AuthError,
    ConfigError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    UpstreamError,
    ValidationError,
    register_secret,
)
from benethos_lexware_office_mcp.ratelimit import TokenBucket

API_KEY = "test-key-0123456789"


class Recorder:
    """A MockTransport handler that replays a scripted list of responses."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self._responses.pop(0) if self._responses else httpx.Response(200)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def calls(self) -> int:
        return len(self.requests)


def make_client(*responses: httpx.Response | Exception, **kw: Any) -> LexwareClient:
    """A client whose bucket and sleep never touch real time."""
    handler = Recorder(*responses)
    settings = Settings(api_key=API_KEY, **kw)

    async def no_sleep(_seconds: float) -> None:
        return None

    client = LexwareClient(
        settings,
        transport=httpx.MockTransport(handler),
        bucket=TokenBucket(1000.0, 100, sleep=no_sleep),
        sleep=no_sleep,
    )
    client.handler = handler  # type: ignore[attr-defined]
    return client


# -- happy path -----------------------------------------------------------


async def test_a_successful_call_sends_the_bearer_token() -> None:
    async with make_client(httpx.Response(200, json={"ok": True})) as client:
        assert await client.get_json("/v1/profile") == {"ok": True}
        sent = client.handler.requests[0]  # type: ignore[attr-defined]
        assert sent.headers["Authorization"] == f"Bearer {API_KEY}"


async def test_a_missing_key_is_refused_before_any_request() -> None:
    client = LexwareClient(
        Settings(), transport=httpx.MockTransport(Recorder()), bucket=TokenBucket(99, 9)
    )
    with pytest.raises(ConfigError):
        await client.request("GET", "/v1/profile")
    await client.aclose()


async def test_profile_rejects_an_unexpected_shape() -> None:
    async with make_client(httpx.Response(200, json=["not", "a", "profile"])) as client:
        with pytest.raises(UpstreamError):
            await client.profile()


async def test_a_malformed_body_is_reported_rather_than_raised_raw() -> None:
    async with make_client(httpx.Response(200, text="<html>nope</html>")) as client:
        with pytest.raises(UpstreamError):
            await client.get_json("/v1/profile")


# -- error mapping --------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, ValidationError),
        (401, AuthError),
        (403, AuthError),
        (404, NotFoundError),
        (406, ValidationError),
        (409, ConflictError),
    ],
)
async def test_status_maps_to_the_right_error(
    status: int, expected: type[Exception]
) -> None:
    async with make_client(httpx.Response(status, json={})) as client:
        with pytest.raises(expected):
            await client.request("GET", "/v1/contacts/abc")


async def test_a_client_error_carries_the_api_s_own_wording() -> None:
    body = {"errorCode": "3000", "message": "voucherDate must not be null"}
    async with make_client(httpx.Response(400, json=body)) as client:
        with pytest.raises(ValidationError) as excinfo:
            await client.request("GET", "/v1/vouchers")
    assert "voucherDate must not be null" in str(excinfo.value)


async def test_a_stale_version_tells_the_caller_to_re_read() -> None:
    """Verified 2026-08-20: a stale version is a 406 naming `version`."""
    body = {"IssueList": [{"source": "version", "type": "validation_failure"}]}
    async with make_client(httpx.Response(406, json=body)) as client:
        with pytest.raises(ConflictError) as excinfo:
            await client.request("PUT", "/v1/contacts/abc")
    assert "current version" in str(excinfo.value)


async def test_a_conflict_does_not_invent_a_version_that_was_never_named() -> None:
    """Verified 2026-08-21: a draft sales document refuses its own download.

    `GET /v1/invoices/{id}/file` answers 409 while the document is a draft,
    and nothing about that is a version conflict. Telling the caller to read
    the record again for a fresher version sends them after a fix that does
    not exist.
    """
    body = {
        "status": 409,
        "error": "Conflict",
        "message": (
            "the sales voucher with id abc and voucher type 'Invoice' is in "
            "status 'draft' and therefore cannot be downloaded"
        ),
    }
    async with make_client(httpx.Response(409, json=body)) as client:
        with pytest.raises(ConflictError) as excinfo:
            await client.request("GET", "/v1/invoices/abc/file")

    message = str(excinfo.value)
    assert "current version" not in message
    assert "status 'draft'" in message


async def test_the_api_key_never_appears_in_an_error() -> None:
    register_secret(API_KEY)
    body = {"message": f"bad token {API_KEY}"}
    async with make_client(httpx.Response(400, json=body)) as client:
        with pytest.raises(ValidationError) as excinfo:
            await client.request("GET", "/v1/profile")
    assert API_KEY not in str(excinfo.value)


# -- retry rules, SPECS section 10.2 --------------------------------------


async def test_a_get_is_retried_after_a_server_error() -> None:
    async with make_client(
        httpx.Response(500), httpx.Response(200, json={"ok": True})
    ) as client:
        assert await client.get_json("/v1/profile") == {"ok": True}
        assert client.handler.calls == 2  # type: ignore[attr-defined]


async def test_a_post_is_never_retried_after_a_server_error() -> None:
    """A 5xx does not say whether the document was created."""
    async with make_client(httpx.Response(500), httpx.Response(200)) as client:
        with pytest.raises(UpstreamError) as excinfo:
            await client.request("POST", "/v1/invoices", json={})
        assert client.handler.calls == 1  # type: ignore[attr-defined]
    assert excinfo.value.outcome_unknown is True
    assert "outcome is unknown" in str(excinfo.value)


async def test_a_post_is_never_retried_after_a_timeout() -> None:
    timeout = httpx.TimeoutException("too slow")
    async with make_client(timeout, httpx.Response(200)) as client:
        with pytest.raises(UpstreamError) as excinfo:
            await client.request("POST", "/v1/invoices", json={})
        assert client.handler.calls == 1  # type: ignore[attr-defined]
    assert excinfo.value.outcome_unknown is True


async def test_a_get_is_retried_after_a_timeout() -> None:
    async with make_client(
        httpx.TimeoutException("too slow"), httpx.Response(200, json={"ok": True})
    ) as client:
        assert await client.get_json("/v1/profile") == {"ok": True}
        assert client.handler.calls == 2  # type: ignore[attr-defined]


async def test_a_put_is_retried_because_the_version_protects_it() -> None:
    async with make_client(httpx.Response(503), httpx.Response(200)) as client:
        await client.request("PUT", "/v1/contacts/abc", json={})
        assert client.handler.calls == 2  # type: ignore[attr-defined]


async def test_a_post_is_retried_after_429_because_it_was_not_performed() -> None:
    """The one failure mode whose outcome the documentation states."""
    async with make_client(httpx.Response(429), httpx.Response(201)) as client:
        await client.request("POST", "/v1/invoices", json={})
        assert client.handler.calls == 2  # type: ignore[attr-defined]


async def test_a_client_error_is_never_retried() -> None:
    async with make_client(httpx.Response(400), httpx.Response(200)) as client:
        with pytest.raises(ValidationError):
            await client.request("GET", "/v1/profile")
        assert client.handler.calls == 1  # type: ignore[attr-defined]


async def test_retries_stop_and_report_rather_than_looping() -> None:
    async with make_client(*[httpx.Response(500)] * 5) as client:
        with pytest.raises(UpstreamError):
            await client.request("GET", "/v1/profile")
        assert client.handler.calls == 3  # type: ignore[attr-defined]


async def test_repeated_rate_limiting_trips_the_breaker() -> None:
    """Hammering after a 429 is what turns a pause into a blocked key."""
    async with make_client(*[httpx.Response(429)] * 10) as client:
        with pytest.raises(RateLimitError) as excinfo:
            await client.request("GET", "/v1/profile")
        assert client.handler.calls == BREAKER_THRESHOLD  # type: ignore[attr-defined]
    assert "whole account" in str(excinfo.value)


async def test_retry_after_is_honoured() -> None:
    slept: list[float] = []

    async def record(seconds: float) -> None:
        slept.append(seconds)

    handler = Recorder(
        httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)
    )
    client = LexwareClient(
        Settings(api_key=API_KEY),
        transport=httpx.MockTransport(handler),
        bucket=TokenBucket(1000.0, 100, sleep=record),
        sleep=record,
    )
    await client.request("GET", "/v1/profile")
    await client.aclose()

    assert max(slept) >= 3.5  # 7 seconds, minus at most half from the jitter


async def test_an_unparsable_retry_after_still_backs_off() -> None:
    async with make_client(
        httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        httpx.Response(200),
    ) as client:
        await client.request("GET", "/v1/profile")
        assert client.handler.calls == 2  # type: ignore[attr-defined]


async def test_every_request_passes_the_bucket() -> None:
    """Including retries, which is where a limiter is most easily bypassed."""
    acquired: list[int] = []

    class CountingBucket(TokenBucket):
        async def acquire(self, tokens: int = 1) -> None:
            acquired.append(tokens)

    handler = Recorder(httpx.Response(500), httpx.Response(500), httpx.Response(200))
    client = LexwareClient(
        Settings(api_key=API_KEY),
        transport=httpx.MockTransport(handler),
        bucket=CountingBucket(1000.0, 100),
        sleep=_no_sleep,
    )
    await client.request("GET", "/v1/profile")
    await client.aclose()

    assert len(acquired) == 3


async def _no_sleep(_seconds: float) -> None:
    return None
