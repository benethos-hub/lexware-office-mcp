"""The line per API call, which replaces the one httpx used to write."""

from __future__ import annotations

import io
import logging

import httpx
import pytest

from benethos_lexware_office_mcp.errors import AuthError, RateLimitError
from benethos_lexware_office_mcp.logbook import configure
from benethos_lexware_office_mcp.logbook.api import _shown
from benethos_lexware_office_mcp.logbook.output import PACKAGE
from helpers import Scripted, always, fast_client

CONTACT = "0b7a5c9e-3f2d-4e1a-9c8b-7d6e5f4a3b2c"


@pytest.fixture
def lines(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """What reaches stderr with the server configured as it configures itself."""
    configure("DEBUG", io.StringIO())
    caplog.set_level(logging.DEBUG, logger=PACKAGE)
    return caplog


async def test_a_call_is_one_line_with_path_status_and_attempt(
    lines: pytest.LogCaptureFixture,
) -> None:
    client = fast_client(always({"content": []}))

    await client.contacts(name="Mustermann")
    await client.aclose()

    (record,) = lines.records
    assert record.levelno == logging.DEBUG
    assert record.name == f"{PACKAGE}.client"
    message = record.getMessage()
    assert message.startswith("GET /v1/contacts 200 in ")
    assert message.endswith("ms, attempt 1")
    assert "Mustermann" not in lines.text


async def test_an_id_is_shown_and_a_name_in_its_place_is_not(
    lines: pytest.LogCaptureFixture,
) -> None:
    client = fast_client(always({}))

    await client.contact(CONTACT)
    await client.contact("Max Mustermann")
    await client.aclose()

    assert f"GET /v1/contacts/{CONTACT} 200" in lines.text
    assert "GET /v1/contacts/~ 200" in lines.text
    assert "Mustermann" not in lines.text


@pytest.mark.parametrize(
    ("endpoint", "shown"),
    [
        ("/v1/recurring-templates", "/v1/recurring-templates"),
        (f"/v1/invoices/{CONTACT}/file", f"/v1/invoices/{CONTACT}/file"),
        ("/v1/contacts/max%40example.com", "/v1/contacts/~"),
        ("/v1/contacts?name=Mustermann", "/v1/contacts"),
    ],
)
def test_only_words_and_uuids_are_shown(endpoint: str, shown: str) -> None:
    assert _shown(endpoint) == shown


async def test_a_retry_is_a_warning_that_says_why_and_when(
    lines: pytest.LogCaptureFixture,
) -> None:
    client = fast_client(Scripted((503, {}), (200, {})))

    await client.profile()
    await client.aclose()

    warnings = [r.getMessage() for r in lines.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].startswith("GET /v1/profile answered 503, attempt 2 follows in")
    assert "attempt 2" in lines.records[-1].getMessage()


async def test_a_timeout_names_the_error_class(
    lines: pytest.LogCaptureFixture,
) -> None:
    client = fast_client(Scripted(httpx.ReadTimeout("read timed out"), (200, {})))

    await client.profile()
    await client.aclose()

    assert "GET /v1/profile got no answer (ReadTimeout), attempt 2" in lines.text


async def test_the_breaker_says_how_long_it_holds(
    lines: pytest.LogCaptureFixture,
) -> None:
    client = fast_client(always({}, status=429))

    with pytest.raises(RateLimitError):
        await client.profile()
    await client.aclose()

    assert "Rate limited 3 times in a row, holding every request for 30 s" in (
        lines.text
    )


async def test_a_rejected_key_is_a_warning_of_its_own(
    lines: pytest.LogCaptureFixture,
) -> None:
    client = fast_client(always({}, status=401))

    with pytest.raises(AuthError):
        await client.profile()
    await client.aclose()

    assert "The API rejected the key" in lines.text


async def test_a_honoured_retry_after_is_noted(
    lines: pytest.LogCaptureFixture,
) -> None:
    client = fast_client(
        Scripted(httpx.Response(429, headers={"Retry-After": "7"}), (200, {}))
    )

    await client.profile()
    await client.aclose()

    assert "Retry-After asked for 7.0 s" in lines.text
