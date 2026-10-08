"""The HTTP client: error mapping and the retry rules. Offline throughout."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from benethos_lexware_office_mcp.api import connection
from benethos_lexware_office_mcp.api.client import LexwareClient
from benethos_lexware_office_mcp.api.connection import BREAKER_THRESHOLD
from benethos_lexware_office_mcp.api.ratelimit import TokenBucket
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
from benethos_lexware_office_mcp.settings import Settings
from helpers import API_KEY, Scripted, fast_client, no_sleep


def make_client(*responses: httpx.Response | Exception, **kw: Any) -> LexwareClient:
    """A client whose bucket and sleep never touch real time."""
    handler = Scripted(*responses)
    client = fast_client(handler, **kw)
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
        Settings(), transport=httpx.MockTransport(Scripted()), bucket=TokenBucket(99, 9)
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


WRITES = [
    ("create_contact", ({},)),
    ("update_contact", ("PLACEHOLDER-CONTACT-1", {})),
    ("create_voucher", ({},)),
    ("update_voucher", ("PLACEHOLDER-VOUCHER-1", {})),
    ("create_article", ({},)),
    ("update_article", ("PLACEHOLDER-ARTICLE-1", {})),
    ("create_sales_document", ("invoices", {})),
    ("upload_file", (b"%PDF", "r.pdf", "application/pdf")),
    ("attach_file", ("PLACEHOLDER-VOUCHER-1", b"%PDF", "r.pdf", "application/pdf")),
]


@pytest.mark.parametrize(("method", "args"), WRITES, ids=[w[0] for w in WRITES])
@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(201, content=b""),
        httpx.Response(200, text="<html>proxy</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
    ],
    ids=["empty", "html", "list"],
)
async def test_an_unreadable_answer_to_a_write_is_an_unknown_outcome(
    method: str, args: tuple[Any, ...], answer: httpx.Response
) -> None:
    """The write went through. What it created is what nobody saw.

    A raw ValueError reached the model as "Error executing tool" and nothing
    else, which reads like a failure worth retrying - a second record.
    """
    async with make_client(answer) as client:
        with pytest.raises(UpstreamError) as excinfo:
            await getattr(client, method)(*args)

    assert excinfo.value.outcome_unknown
    assert "Check whether the record exists" in str(excinfo.value)
    assert client.handler.calls == 1  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (
            lambda c: c.update_contact("x/../../articles/y", {}),
            b"/v1/contacts/x%2F..%2F..%2Farticles%2Fy",
        ),
        (lambda c: c.delete_article("a?b#c"), b"/v1/articles/a%3Fb%23c"),
        (lambda c: c.voucher("v/files"), b"/v1/vouchers/v%2Ffiles"),
        (
            lambda c: c.document_file("invoices", "../contacts"),
            b"/v1/invoices/..%2Fcontacts/file",
        ),
    ],
    ids=["put", "delete", "get", "download"],
)
async def test_an_id_stays_inside_its_path_segment(call: Any, expected: bytes) -> None:
    """Ids come from the model. A slash in one must not reach another path."""
    async with make_client(httpx.Response(200, json={})) as client:
        await call(client)
        sent = client.handler.requests[0]  # type: ignore[attr-defined]

    assert sent.url.raw_path == expected


@pytest.mark.parametrize("bad", ["", " ", ".", ".."])
async def test_an_id_that_a_url_would_resolve_away_is_refused(bad: str) -> None:
    async with make_client() as client:
        with pytest.raises(ValidationError, match="not an id"):
            await client.delete_article(bad)

        assert client.handler.calls == 0  # type: ignore[attr-defined]


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


async def test_a_refused_body_names_the_fields_it_refused() -> None:
    """Measured 2026-08-21 against `POST /v1/articles` with fields missing.

    A refused body carries `details`, not an `IssueList`, and the two share no
    field names. The API's own message points at that list - "please see
    details list for specific causes" - so dropping it hands the caller a
    pointer to something they were never given.
    """
    body = {
        "status": 406,
        "message": "Validation failed for request. Please see details list.",
        "details": [
            {
                "violation": "NOTNULL",
                "field": "price",
                "message": "darf nicht null sein",
            },
            {
                "violation": "NOTEMPTY",
                "field": "unitName",
                "message": "darf nicht leer sein",
            },
        ],
    }
    async with make_client(httpx.Response(406, json=body)) as client:
        with pytest.raises(ValidationError) as excinfo:
            await client.request("POST", "/v1/articles", json={})
    message = str(excinfo.value)
    assert "price: NOTNULL" in message
    assert "unitName: NOTEMPTY" in message
    assert "darf nicht" not in message, (
        "the localized half says no more than the violation"
    )


async def test_a_stale_version_in_the_details_shape_is_still_a_conflict() -> None:
    """The shape changes, the meaning does not."""
    body = {"details": [{"violation": "STALE", "field": "version"}]}
    async with make_client(httpx.Response(406, json=body)) as client:
        with pytest.raises(ConflictError):
            await client.request("PUT", "/v1/articles/abc")


async def test_a_stale_version_after_a_lost_answer_blames_the_first_attempt() -> None:
    """The update went through, its answer did not, and the retry is stale.

    Telling the caller somebody changed the record sends it to apply the
    same change twice.
    """
    stale = {"IssueList": [{"source": "version", "i18nKey": "invalid_value"}]}
    async with make_client(
        httpx.TimeoutException("too slow"), httpx.Response(406, json=stale)
    ) as client:
        with pytest.raises(ConflictError) as excinfo:
            await client.request("PUT", "/v1/contacts/abc", json={})

    assert "most likely carried out" in str(excinfo.value)
    assert "changed since it was read" not in str(excinfo.value)
    assert excinfo.value.status == 406


async def test_a_conflict_on_a_retried_read_is_not_blamed_on_the_read() -> None:
    """A GET changes nothing, so its first attempt cannot have moved anything.

    The file of a draft answers 409 for its own reason, and that reason is
    what the caller needs.
    """
    body = {
        "status": 409,
        "message": "Document with status 'draft' does not provide a file.",
    }
    async with make_client(
        httpx.TimeoutException("too slow"), httpx.Response(409, json=body)
    ) as client:
        with pytest.raises(ConflictError) as excinfo:
            await client.request("GET", "/v1/invoices/abc/file")

    assert "most likely carried out" not in str(excinfo.value)
    assert "status 'draft'" in str(excinfo.value)


async def test_a_stale_version_on_the_first_attempt_is_somebody_elses() -> None:
    stale = {"IssueList": [{"source": "version", "i18nKey": "invalid_value"}]}
    async with make_client(httpx.Response(406, json=stale)) as client:
        with pytest.raises(ConflictError) as excinfo:
            await client.request("PUT", "/v1/contacts/abc", json={})

    assert "changed since it was read" in str(excinfo.value)


async def test_a_version_that_was_never_sent_is_not_a_stale_one() -> None:
    """Measured 2026-08-21 against `PUT /v1/articles/{id}` with a bare body.

    The missing `version` comes back as a `NOTNULL` violation naming that
    field. Reading the field name alone would call it a version mismatch and
    send the caller to re-read a record that is not the problem.
    """
    body = {"details": [{"violation": "NOTNULL", "field": "version"}]}
    async with make_client(httpx.Response(406, json=body)) as client:
        with pytest.raises(ValidationError) as excinfo:
            await client.request("PUT", "/v1/articles/abc", json={})
    assert "version: NOTNULL" in str(excinfo.value)
    assert "changed since" not in str(excinfo.value)


async def test_a_missing_version_in_the_issue_list_shape_is_not_a_stale_one() -> None:
    """The same absence in the other shape: `i18nKey`, not `violation`."""
    body = {
        "IssueList": [
            {
                "i18nKey": "missing_entity",
                "source": "version",
                "type": "validation_failure",
            }
        ]
    }
    async with make_client(httpx.Response(406, json=body)) as client:
        with pytest.raises(ValidationError) as excinfo:
            await client.request("PUT", "/v1/contacts/abc", json={})
    assert "version: missing_entity" in str(excinfo.value)
    assert "changed since" not in str(excinfo.value)


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


def _undecodable() -> httpx.Response:
    """Announces gzip, carries none: httpx raises DecodingError reading it."""
    return httpx.Response(
        201,
        headers={"Content-Encoding": "gzip"},
        stream=httpx.ByteStream(b"not gzip at all"),
    )


async def test_a_post_whose_answer_cannot_be_decoded_has_an_unknown_outcome() -> None:
    """Not a TransportError, and it used to escape as a crash."""
    async with make_client(_undecodable(), httpx.Response(200)) as client:
        with pytest.raises(UpstreamError) as excinfo:
            await client.request("POST", "/v1/invoices", json={})
        assert client.handler.calls == 1  # type: ignore[attr-defined]
    assert excinfo.value.outcome_unknown is True


async def test_a_get_whose_answer_cannot_be_decoded_is_retried() -> None:
    async with make_client(
        _undecodable(), httpx.Response(200, json={"ok": True})
    ) as client:
        assert await client.get_json("/v1/profile") == {"ok": True}


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


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize(
    "lost",
    [httpx.ReadTimeout("slow"), httpx.ConnectError("reset"), httpx.Response(502)],
    ids=["timeout", "connection", "bad gateway"],
)
async def test_an_update_out_of_retries_has_an_unknown_outcome(
    method: str, lost: httpx.Response | Exception
) -> None:
    """Any of the three attempts may have been carried out. Reported as a
    plain failure, the caller sent it again into a stale version or a 404."""
    async with make_client(lost, lost, lost) as client:
        with pytest.raises(UpstreamError) as excinfo:
            await client.request(method, "/v1/contacts/abc", json={})
        assert client.handler.calls == 3  # type: ignore[attr-defined]
    assert excinfo.value.outcome_unknown is True


async def test_a_read_out_of_retries_has_nothing_unknown() -> None:
    async with make_client(*[httpx.ReadTimeout("slow")] * 3) as client:
        with pytest.raises(UpstreamError) as excinfo:
            await client.request("GET", "/v1/profile")
    assert excinfo.value.outcome_unknown is False


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


async def test_a_transport_error_ends_the_rate_limit_streak() -> None:
    """The breaker counts consecutive 429s. A timeout between them is not
    one, and without the reset two 429s either side of it tripped it."""
    async with make_client(
        httpx.Response(429),
        httpx.Response(429),
        httpx.ConnectTimeout("slow"),
        httpx.Response(429),
        httpx.Response(200, json={}),
    ) as client:
        with pytest.raises(UpstreamError):
            await client.request("GET", "/v1/profile")

        response = await client.request("GET", "/v1/profile")

    assert response.status_code == 200


@pytest.mark.parametrize(
    "lost",
    [httpx.ReadTimeout("slow"), httpx.Response(502)],
    ids=["timeout", "bad gateway"],
)
async def test_a_retried_delete_that_finds_nothing_has_worked(
    lost: httpx.Response | Exception,
) -> None:
    """The first attempt deleted it and its answer was lost. The retry's 404
    is the evidence, not a sign that the article never existed."""
    async with make_client(lost, httpx.Response(404)) as client:
        await client.delete_article("PLACEHOLDER-ARTICLE-1")

        assert client.handler.calls == 2  # type: ignore[attr-defined]


async def test_a_delete_that_finds_nothing_at_once_is_still_a_404() -> None:
    async with make_client(httpx.Response(404)) as client:
        with pytest.raises(NotFoundError):
            await client.delete_article("PLACEHOLDER-ARTICLE-1")


async def test_a_delete_retried_only_after_429_is_still_a_404() -> None:
    """A 429 was certainly not performed, so it proves nothing about a 404."""
    async with make_client(httpx.Response(429), httpx.Response(404)) as client:
        with pytest.raises(NotFoundError):
            await client.delete_article("PLACEHOLDER-ARTICLE-1")


async def test_retry_after_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """In full: the jitter shortens the computed delay, never the server's."""
    monkeypatch.setattr(connection.random, "random", lambda: 0.0)
    slept: list[float] = []

    async def record(seconds: float) -> None:
        slept.append(seconds)

    handler = Scripted(
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

    assert max(slept) >= 7


@pytest.mark.parametrize("seconds", ["86400", "inf", "nan", "9"])
async def test_a_retry_after_beyond_the_cap_is_not_slept_through(seconds: str) -> None:
    """A day, or for ever, inside a tool call is worse than an answer now."""
    slept: list[float] = []

    async def record(delay: float) -> None:
        slept.append(delay)

    handler = Scripted(
        httpx.Response(429, headers={"Retry-After": seconds}), httpx.Response(200)
    )
    client = LexwareClient(
        Settings(api_key=API_KEY),
        transport=httpx.MockTransport(handler),
        bucket=TokenBucket(1000.0, 100, sleep=record),
        sleep=record,
    )
    with pytest.raises(RateLimitError, match="longer than this call waits"):
        await client.request("GET", "/v1/profile")
    await client.aclose()

    assert handler.calls == 1
    assert all(delay <= 8.0 for delay in slept)


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

    handler = Scripted(httpx.Response(500), httpx.Response(500), httpx.Response(200))
    client = LexwareClient(
        Settings(api_key=API_KEY),
        transport=httpx.MockTransport(handler),
        bucket=CountingBucket(1000.0, 100),
        sleep=no_sleep,
    )
    await client.request("GET", "/v1/profile")
    await client.aclose()

    assert len(acquired) == 3
