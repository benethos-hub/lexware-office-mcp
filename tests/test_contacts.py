"""Contacts: the client calls, the trimming, and the four tools.

The fixtures are shapes a live account actually returned on 2026-08-20, with
placeholder identifiers: a company and a person contact, the page envelope
including the ``sort`` block that gets dropped, and the error bodies. The
write half was exercised against the same account, which is where the merging
behaviour asserted here comes from. See SPECS.md section 5.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp import formatting
from benethos_lexware_office_mcp.client import ClientProvider, LexwareClient
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import build_server

API_KEY = "test-key-0123456789"

COMPANY = {
    "id": "PLACEHOLDER-CONTACT-1",
    "organizationId": "PLACEHOLDER-ORG-ID",
    "version": 3,
    "roles": {"customer": {"number": 10001}, "vendor": {"number": 70001}},
    "company": {
        "name": "Beispiel GmbH",
        "taxNumber": "12345/67890",
        "vatRegistrationId": "DE123456789",
        "allowTaxFreeInvoices": False,
        "contactPersons": [
            {
                "salutation": "Frau",
                "firstName": "Alex",
                "lastName": "Muster",
                "primary": True,
                "emailAddress": "alex@example.invalid",
                "phoneNumber": "+49 30 000000",
            }
        ],
    },
    "addresses": {
        "billing": [
            {
                "street": "Musterweg 1",
                "zip": "10115",
                "city": "Berlin",
                "countryCode": "DE",
                "supplement": None,
            }
        ]
    },
    "emailAddresses": {
        "business": ["office@example.invalid"],
        "private": ["private@example.invalid"],
        "office": [],
    },
    "phoneNumbers": {"business": ["+49 30 111111"], "mobile": ["+49 170 222222"]},
    "note": "",
    "archived": False,
}

PERSON = {
    "id": "PLACEHOLDER-CONTACT-2",
    "organizationId": "PLACEHOLDER-ORG-ID",
    "version": 1,
    "roles": {"customer": {"number": 10002}},
    "person": {"salutation": "Herr", "firstName": "Chris", "lastName": "Beispiel"},
    "emailAddresses": {"private": ["chris@example.invalid"]},
    "phoneNumbers": {"mobile": ["+49 170 333333"]},
    "archived": True,
}

# The envelope exactly as a live account returned it on 2026-08-20, including
# the `sort` block that gets dropped.
PAGE = {
    "content": [COMPANY, PERSON],
    "first": True,
    "last": True,
    "number": 0,
    "numberOfElements": 2,
    "size": 25,
    "sort": [
        {
            "ascending": True,
            "direction": "ASC",
            "ignoreCase": False,
            "nullHandling": "NATIVE",
            "property": "name",
        },
        {
            "ascending": True,
            "direction": "ASC",
            "ignoreCase": False,
            "nullHandling": "NATIVE",
            "property": "lastModifiedDate",
        },
    ],
    "totalElements": 2,
    "totalPages": 1,
}


async def _no_sleep(_seconds: float) -> None:
    return None


class Capturing:
    """Answers every request with ``payload`` and remembers what was asked."""

    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self._status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status, json=self._payload)

    @property
    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(str(self.requests[-1].url)).query)

    @property
    def path(self) -> str:
        return urlparse(str(self.requests[-1].url)).path


def make_client(handler: Capturing) -> LexwareClient:
    return LexwareClient(
        Settings(api_key=API_KEY),
        transport=httpx.MockTransport(handler),
        bucket=TokenBucket(1000.0, 100, sleep=_no_sleep),
        sleep=_no_sleep,
    )


def make_provider(handler: Capturing, **kw: Any) -> ClientProvider:
    return ClientProvider(
        Settings(api_key=API_KEY, **kw),
        transport=httpx.MockTransport(handler),
        bucket=TokenBucket(1000.0, 100, sleep=_no_sleep),
        sleep=_no_sleep,
    )


# -- client ---------------------------------------------------------------


async def test_only_the_filters_that_were_given_are_sent() -> None:
    """An unset filter has to be absent, not the string "None"."""
    handler = Capturing(PAGE)
    async with make_client(handler) as client:
        await client.contacts(name="Beispiel", page=2, size=50)

    assert handler.query == {"page": ["2"], "size": ["50"], "name": ["Beispiel"]}


async def test_every_filter_reaches_the_query_string() -> None:
    handler = Capturing(PAGE)
    async with make_client(handler) as client:
        await client.contacts(
            name="Beispiel", email="example", number=10001, customer=True, vendor=True
        )

    query = handler.query
    assert query["name"] == ["Beispiel"]
    assert query["email"] == ["example"]
    assert query["number"] == ["10001"]
    # Lowercase, which is what the API expects for a boolean.
    assert query["customer"] == ["true"]
    assert query["vendor"] == ["true"]


async def test_one_page_is_fetched_and_no_more() -> None:
    """Walking every page would spend the account's whole rate limit."""
    handler = Capturing({**PAGE, "totalPages": 40, "last": False})
    async with make_client(handler) as client:
        await client.contacts()

    assert len(handler.requests) == 1


async def test_a_single_contact_is_read_by_id() -> None:
    handler = Capturing(COMPANY)
    async with make_client(handler) as client:
        await client.contact("PLACEHOLDER-CONTACT-1")

    assert handler.path == "/v1/contacts/PLACEHOLDER-CONTACT-1"


async def test_an_unknown_contact_id_is_a_not_found() -> None:
    """Verified against a live account 2026-08-20: an unused UUID gives 404."""
    handler = Capturing({}, status=404)
    async with make_client(handler) as client:
        with pytest.raises(NotFoundError):
            await client.contact("00000000-0000-0000-0000-000000000000")


async def test_a_rejected_filter_names_the_field_and_the_reason() -> None:
    """The live 400 body carries only an IssueList, with no message at all.

    Confirmed on 2026-08-20 by sending ``number=X``. Reporting only "the API
    rejected it" would throw away the one useful part of the response.
    """
    body = {
        "IssueList": [
            {
                "i18nKey": "invalid_value",
                "source": "number",
                "type": "validation_failure",
            }
        ],
        "requestId": "PLACEHOLDER-REQUEST-ID",
    }
    handler = Capturing(body, status=400)
    async with make_client(handler) as client:
        with pytest.raises(ValidationError) as excinfo:
            await client.contacts()

    assert "number" in str(excinfo.value)
    assert "invalid_value" in str(excinfo.value)


# -- formatting -----------------------------------------------------------


def test_a_company_row_carries_identity_and_one_way_to_make_contact() -> None:
    row = formatting.contact_row(COMPANY)
    assert row["id"] == "PLACEHOLDER-CONTACT-1"
    assert row["version"] == 3
    assert row["name"] == "Beispiel GmbH"
    assert row["type"] == "company"
    assert row["roles"] == ["customer", "vendor"]
    assert row["customerNumber"] == 10001
    assert row["vendorNumber"] == 70001


def test_a_person_row_is_named_from_the_person_block() -> None:
    row = formatting.contact_row(PERSON)
    assert row["name"] == "Chris Beispiel"
    assert row["type"] == "person"
    # The salutation identifies nobody and is paid for on every row.
    assert "Herr" not in str(row)


def test_the_business_address_wins_over_the_private_one() -> None:
    row = formatting.contact_row(COMPANY)
    assert row["email"] == "office@example.invalid"
    assert row["phone"] == "+49 30 111111"


def test_a_kind_the_contact_does_not_have_is_skipped() -> None:
    """The API sends empty lists for unused kinds, which must not win."""
    row = formatting.contact_row(PERSON)
    assert row["email"] == "chris@example.invalid"
    assert row["phone"] == "+49 170 333333"


def test_a_row_without_any_way_to_make_contact_omits_the_fields() -> None:
    row = formatting.contact_row(
        {"id": "x", "version": 1, "company": {"name": "Nur Name GmbH"}}
    )
    assert "email" not in row
    assert "phone" not in row
    assert "roles" not in row


def test_a_block_that_exists_but_is_all_empty_yields_nothing() -> None:
    """The API sends the container with empty lists rather than omitting it."""
    row = formatting.contact_row(
        {
            "id": "x",
            "company": {"name": "Leer GmbH"},
            "emailAddresses": {"business": [], "private": []},
            "phoneNumbers": {},
        }
    )
    assert "email" not in row
    assert "phone" not in row


async def test_an_issue_with_only_one_half_still_says_something() -> None:
    """Not every issue carries both a source and a key, and half is not none."""
    body = {"IssueList": [{"source": "voucherDate"}, {"i18nKey": "missing_value"}, "?"]}
    handler = Capturing(body, status=400)
    async with make_client(handler) as client:
        with pytest.raises(ValidationError) as excinfo:
            await client.contacts()

    assert "voucherDate" in str(excinfo.value)
    assert "missing_value" in str(excinfo.value)


def test_archived_is_marked_only_when_it_is_true() -> None:
    assert formatting.contact_row(PERSON)["archived"] is True
    assert "archived" not in formatting.contact_row(COMPANY)


def test_the_page_keeps_what_is_needed_to_ask_for_the_next_one() -> None:
    page = formatting.contacts_page(PAGE)["page"]
    assert page == {
        "number": 0,
        "size": 25,
        "totalElements": 2,
        "totalPages": 1,
        "last": True,
    }


def test_the_sort_block_is_dropped() -> None:
    """Five fields per sort key, identical on every response."""
    assert "nullHandling" not in str(formatting.contacts_page(PAGE))


def test_an_empty_account_still_reports_its_page() -> None:
    """Zero is an answer. Verified live: an empty account returns exactly this."""
    empty = {
        "content": [],
        "first": True,
        "last": True,
        "number": 0,
        "numberOfElements": 0,
        "size": 25,
        "totalElements": 0,
        "totalPages": 0,
    }
    result = formatting.contacts_page(empty)
    assert result["contacts"] == []
    assert result["page"]["totalElements"] == 0
    assert result["page"]["number"] == 0


def test_the_full_contact_drops_the_organization_id() -> None:
    """It is the same on every record and get_profile already answers it."""
    full = formatting.contact(COMPANY)
    assert "organizationId" not in full
    assert full["company"]["name"] == "Beispiel GmbH"
    assert full["addresses"]["billing"][0]["city"] == "Berlin"


def test_the_full_contact_keeps_the_version_for_a_later_update() -> None:
    assert formatting.contact(COMPANY)["version"] == 3


def test_the_full_contact_keeps_false_but_drops_empty() -> None:
    full = formatting.contact(COMPANY)
    assert full["company"]["allowTaxFreeInvoices"] is False
    assert "note" not in full
    assert "supplement" not in full["addresses"]["billing"][0]


# -- tools ----------------------------------------------------------------


async def test_both_tools_are_listed_in_read_mode() -> None:
    names = [tool.name for tool in await build_server(Settings()).list_tools()]
    assert "search_contacts" in names
    assert "get_contact" in names


async def test_the_search_description_points_at_the_follow_up_tool() -> None:
    server = build_server(Settings())
    tool = next(t for t in await server.list_tools() if t.name == "search_contacts")
    assert tool.description is not None
    assert "get_contact" in tool.description
    assert "one api call" in tool.description.lower()


async def test_the_schema_stops_a_two_character_search_before_it_is_sent() -> None:
    """The API rejects it with a message about "size", which explains nothing."""
    handler = Capturing(PAGE)
    provider = make_provider(handler)
    server = build_server(Settings(api_key=API_KEY), provider)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("search_contacts", {"name": "ab"})

    assert "at least 3 characters" in str(excinfo.value)
    assert handler.requests == [], "the call reached the API anyway"
    await provider.aclose()


async def test_search_contacts_returns_rows_and_page_info() -> None:
    handler = Capturing(PAGE)
    provider = make_provider(handler)
    server = build_server(Settings(api_key=API_KEY), provider)

    result = await server.call_tool("search_contacts", {"name": "Beispiel"})

    assert result.is_error is not True
    payload = result.structured_content
    assert payload is not None
    assert [row["name"] for row in payload["contacts"]] == [
        "Beispiel GmbH",
        "Chris Beispiel",
    ]
    assert payload["page"]["totalElements"] == 2
    await provider.aclose()


async def test_the_role_filter_becomes_the_flag_the_api_understands() -> None:
    handler = Capturing(PAGE)
    provider = make_provider(handler)
    server = build_server(Settings(api_key=API_KEY), provider)

    await server.call_tool("search_contacts", {"role": "vendor"})

    assert handler.query.get("vendor") == ["true"]
    # Only the asked-for role is constrained, the other is left unset.
    assert "customer" not in handler.query
    await provider.aclose()


async def test_role_any_constrains_nothing() -> None:
    handler = Capturing(PAGE)
    provider = make_provider(handler)
    server = build_server(Settings(api_key=API_KEY), provider)

    await server.call_tool("search_contacts", {})

    assert "customer" not in handler.query
    assert "vendor" not in handler.query
    await provider.aclose()


async def test_the_page_size_default_comes_from_the_settings() -> None:
    handler = Capturing(PAGE)
    provider = make_provider(handler, page_size=7)
    server = build_server(Settings(api_key=API_KEY, page_size=7), provider)

    await server.call_tool("search_contacts", {})

    assert handler.query["size"] == ["7"]
    await provider.aclose()


async def test_get_contact_returns_the_full_record() -> None:
    handler = Capturing(COMPANY)
    provider = make_provider(handler)
    server = build_server(Settings(api_key=API_KEY), provider)

    result = await server.call_tool(
        "get_contact", {"contact_id": "PLACEHOLDER-CONTACT-1"}
    )

    payload = result.structured_content
    assert payload is not None
    assert payload["addresses"]["billing"][0]["zip"] == "10115"
    assert handler.path == "/v1/contacts/PLACEHOLDER-CONTACT-1"
    await provider.aclose()


# -- writing --------------------------------------------------------------


class Scripted:
    """Answers a scripted sequence, and remembers what it was sent."""

    def __init__(self, *responses: tuple[int, Any]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, payload = self._responses.pop(0) if self._responses else (200, {})
        return httpx.Response(status, json=payload)

    @property
    def methods(self) -> list[str]:
        return [request.method for request in self.requests]

    def body(self, index: int) -> Any:
        return json.loads(self.requests[index].content)


CREATED = {
    "id": "PLACEHOLDER-CONTACT-3",
    "resourceUri": "https://api.lexware.io/v1/contacts/PLACEHOLDER-CONTACT-3",
    "createdDate": "2026-08-20T15:49:29.076+02:00",
    "updatedDate": "2026-08-20T15:49:29.080+02:00",
    "version": 1,
}


def write_server(handler: Scripted) -> tuple[Any, ClientProvider]:
    settings = Settings(api_key=API_KEY)
    provider = ClientProvider(
        settings,
        transport=httpx.MockTransport(handler),
        bucket=TokenBucket(1000.0, 100, sleep=_no_sleep),
        sleep=_no_sleep,
    )
    return build_server(settings, provider), provider


async def test_the_contact_group_is_offered_as_the_file_names_it(
    tmp_path: Path,
) -> None:
    """Reading and writing tools are chosen one by one, not in blocks."""
    flags = tmp_path / "tools.json"
    flags.write_text(
        '{"search_contacts": true, "get_contact": true, "create_contact": true,'
        ' "update_contact": false}',
        encoding="utf-8",
    )

    names = {
        tool.name
        for tool in await build_server(Settings(tool_policy_path=flags)).list_tools()
    }

    assert names == {"search_contacts", "get_contact", "create_contact"}


async def test_create_contact_sends_what_the_api_requires() -> None:
    handler = Scripted((201, CREATED))
    server, provider = write_server(handler)

    result = await server.call_tool(
        "create_contact",
        {
            "kind": "company",
            "name": "Neu GmbH",
            "roles": ["customer", "vendor"],
            "email": "neu@example.invalid",
            "billing_address": {
                "street": "Musterweg 1",
                "zip": "10115",
                "city": "Berlin",
                "country_code": "DE",
            },
        },
    )

    assert handler.methods == ["POST"]
    body = handler.body(0)
    assert body["version"] == 0
    assert body["roles"] == {"customer": {}, "vendor": {}}
    assert body["company"] == {"name": "Neu GmbH"}
    assert body["addresses"]["billing"][0]["countryCode"] == "DE"
    assert result.structured_content is not None
    assert result.structured_content["id"] == "PLACEHOLDER-CONTACT-3"
    await provider.aclose()


async def test_a_create_is_one_call_and_is_not_retried() -> None:
    """A retried POST is a second contact nobody asked for."""
    handler = Scripted((500, {}), (201, CREATED))
    server, provider = write_server(handler)

    with pytest.raises(ToolError):
        await server.call_tool(
            "create_contact",
            {"kind": "company", "name": "Neu GmbH", "roles": ["customer"]},
        )

    assert len(handler.requests) == 1
    await provider.aclose()


async def test_update_contact_reads_the_record_before_replacing_it() -> None:
    """The API replaces rather than patches, so the current record is the base."""
    handler = Scripted((200, COMPANY), (200, CREATED))
    server, provider = write_server(handler)

    await server.call_tool(
        "update_contact",
        {
            "contact_id": "PLACEHOLDER-CONTACT-1",
            "version": 3,
            "email": "neu@example.invalid",
        },
    )

    assert handler.methods == ["GET", "PUT"]
    sent = handler.body(1)
    # The one change asked for.
    assert sent["emailAddresses"]["business"] == ["neu@example.invalid"]
    # And everything that was not asked about, still there.
    assert sent["addresses"] == COMPANY["addresses"]
    assert sent["company"]["taxNumber"] == "12345/67890"
    assert sent["version"] == 3
    await provider.aclose()


async def test_a_stale_version_is_refused_before_anything_is_written() -> None:
    """Verified live: the API answers this with 406, after the round trip."""
    handler = Scripted((200, COMPANY), (200, CREATED))
    server, provider = write_server(handler)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(
            "update_contact",
            {"contact_id": "PLACEHOLDER-CONTACT-1", "version": 1, "note": "nope"},
        )

    assert "version 3" in str(excinfo.value)
    assert handler.methods == ["GET"], "the update was sent anyway"
    await provider.aclose()


async def test_a_stale_version_from_the_api_is_a_conflict() -> None:
    """406 naming `version` is the API's way of saying somebody else was first.

    Live body, 2026-08-20. Reporting it as a plain validation error would tell
    the caller to fix their input, when the fix is to read the record again.
    """
    body = {
        "IssueList": [
            {
                "i18nKey": "invalid_value",
                "source": "version",
                "type": "validation_failure",
            }
        ]
    }
    handler = Capturing(body, status=406)
    async with make_client(handler) as client:
        with pytest.raises(ConflictError) as excinfo:
            await client.update_contact("PLACEHOLDER-CONTACT-1", {"version": 1})

    assert "read it" in str(excinfo.value).lower()


async def test_another_406_is_still_a_validation_error() -> None:
    """Contacts answer a missing role with 406 too, and that is the caller's bug."""
    body = {
        "IssueList": [
            {
                "i18nKey": "missing_entity",
                "source": "company or person",
                "type": "validation_failure",
            }
        ]
    }
    handler = Capturing(body, status=406)
    async with make_client(handler) as client:
        with pytest.raises(ValidationError) as excinfo:
            await client.create_contact({"version": 0})

    assert "company or person" in str(excinfo.value)
