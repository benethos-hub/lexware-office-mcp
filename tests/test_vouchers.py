"""The voucher list, bookkeeping vouchers, payments, and the five tools.

Every fixture here is a shape the live API returned on 2026-08-20, with
placeholder identifiers. The write half was exercised against the same test
account, which is where two of the assertions below come from: that a PUT must
not echo ``voucherStatus``, and that payment information does not exist for a
voucher that has not been booked.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp import formatting, policy
from benethos_lexware_office_mcp.client import ClientProvider, LexwareClient
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.payloads import VoucherItem, voucher_body
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import build_server

API_KEY = "test-key-0123456789"
CATEGORY = "PLACEHOLDER-CATEGORY-ID"

VOUCHER = {
    "id": "PLACEHOLDER-VOUCHER-1",
    "organizationId": "PLACEHOLDER-ORG-ID",
    "type": "salesinvoice",
    "voucherStatus": "unchecked",
    "voucherNumber": "MCP-0001",
    "voucherDate": "2026-08-19T00:00:00.000+02:00",
    "totalGrossAmount": 238.0,
    "totalTaxAmount": 38.0,
    "taxType": "gross",
    "useCollectiveContact": True,
    "contactName": "Sammelkunde",
    "remark": "a note",
    "voucherItems": [
        {
            "amount": 238.0,
            "taxAmount": 38.0,
            "taxRatePercent": 19.0,
            "categoryId": CATEGORY,
        }
    ],
    "files": [],
    "createdDate": "2026-08-20T16:22:21.258+02:00",
    "updatedDate": "2026-08-20T16:22:21.258+02:00",
    "version": 3,
}

ROW = {
    "id": "PLACEHOLDER-VOUCHER-1",
    "voucherType": "salesinvoice",
    "voucherStatus": "open",
    "voucherNumber": "MCP-0001",
    "voucherDate": "2026-08-20T00:00:00.000+02:00",
    "createdDate": "2026-08-20T16:17:41.000+02:00",
    "updatedDate": "2026-08-20T16:17:41.000+02:00",
    "dueDate": "2026-08-20T00:00:00.000+02:00",
    "contactName": "Sammelkunde",
    "totalAmount": 119.0,
    "openAmount": 119.0,
    "currency": "EUR",
    "archived": False,
}

PAGE = {
    "content": [ROW],
    "first": True,
    "last": True,
    "number": 0,
    "numberOfElements": 1,
    "size": 25,
    "sort": [{"property": "voucherDate", "nullHandling": "NATIVE"}],
    "totalElements": 1,
    "totalPages": 1,
}

PAYMENTS = {
    "openAmount": 0.0,
    "paymentStatus": "paid",
    "currency": "EUR",
    "voucherType": "salesinvoice",
    "paymentItems": [],
    "voucherStatus": "paid",
}

WRITTEN = {
    "id": "PLACEHOLDER-VOUCHER-1",
    "resourceUri": "https://api.lexware.io/v1/vouchers/PLACEHOLDER-VOUCHER-1",
    "createdDate": "2026-08-20T16:22:21.258+02:00",
    "updatedDate": "2026-08-20T16:22:21.258+02:00",
    "version": 0,
}

LINE = {
    "amount": 238.0,
    "tax_amount": 38.0,
    "tax_rate_percent": 19,
    "category_id": CATEGORY,
}


@pytest.fixture(autouse=True)
def _restore_mode() -> Iterator[None]:
    previous = policy.active_mode()
    yield
    policy.set_active_mode(previous)


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


def server_for(handler: Scripted, mode: str = "read") -> tuple[Any, ClientProvider]:
    settings = Settings(api_key=API_KEY, mode=mode)  # type: ignore[arg-type]
    provider = ClientProvider(
        settings,
        transport=httpx.MockTransport(handler),
        bucket=TokenBucket(1000.0, 100, sleep=_no_sleep),
        sleep=_no_sleep,
    )
    return build_server(settings, provider), provider


# -- client ---------------------------------------------------------------


async def test_the_two_required_parameters_are_always_sent() -> None:
    """The API refuses the request without them, so no caller may omit them."""
    handler = Scripted((200, PAGE))
    async with make_client(handler) as client:
        await client.voucherlist(voucher_type="any", voucher_status="any")

    assert handler.query["voucherType"] == ["any"]
    assert handler.query["voucherStatus"] == ["any"]


async def test_the_optional_filters_reach_the_query_string() -> None:
    handler = Scripted((200, PAGE))
    async with make_client(handler) as client:
        await client.voucherlist(
            voucher_type="invoice",
            voucher_status="open",
            contact_id="PLACEHOLDER-CONTACT-1",
            voucher_date_from="2026-01-01",
            voucher_date_to="2026-12-31",
            only_overdue=True,
            archived=False,
            sort="voucherDate,ASC",
        )

    query = handler.query
    assert query["contactId"] == ["PLACEHOLDER-CONTACT-1"]
    assert query["voucherDateFrom"] == ["2026-01-01"]
    assert query["voucherDateTo"] == ["2026-12-31"]
    assert query["onlyOverdue"] == ["true"]
    assert query["archived"] == ["false"], "a false filter must not be dropped"
    assert query["sort"] == ["voucherDate,ASC"]
    assert "onlyOpen" not in query


async def test_only_one_page_is_fetched() -> None:
    handler = Scripted((200, {**PAGE, "totalPages": 40, "last": False}))
    async with make_client(handler) as client:
        await client.voucherlist(voucher_type="any", voucher_status="any")

    assert len(handler.requests) == 1


async def test_payments_are_read_by_the_voucher_id() -> None:
    handler = Scripted((200, PAYMENTS))
    async with make_client(handler) as client:
        await client.payments("PLACEHOLDER-VOUCHER-1")

    assert handler.path == "/v1/payments/PLACEHOLDER-VOUCHER-1"


# -- formatting -----------------------------------------------------------


def test_a_row_drops_the_dates_that_only_say_when_it_was_typed_in() -> None:
    row = formatting.voucher_row(ROW)
    assert "createdDate" not in row
    assert "updatedDate" not in row
    assert row["voucherDate"].startswith("2026-08-20")
    assert row["dueDate"].startswith("2026-08-20")


def test_a_row_keeps_what_a_caller_chooses_by() -> None:
    row = formatting.voucher_row(ROW)
    assert row["id"] == "PLACEHOLDER-VOUCHER-1"
    assert row["voucherType"] == "salesinvoice"
    assert row["voucherStatus"] == "open"
    assert row["totalAmount"] == 119.0
    assert row["openAmount"] == 119.0
    assert row["currency"] == "EUR"


def test_archived_is_marked_only_when_it_is_true() -> None:
    assert "archived" not in formatting.voucher_row(ROW)
    assert formatting.voucher_row({**ROW, "archived": True})["archived"] is True


def test_a_settled_voucher_reports_a_zero_open_amount() -> None:
    """Zero is the answer to "is it paid", so compact must not eat it."""
    result = formatting.payments(PAYMENTS)
    assert result["openAmount"] == 0.0
    assert result["paymentStatus"] == "paid"
    assert "paymentItems" not in result, "an empty list is dropped"


def test_the_full_voucher_drops_the_organization_id() -> None:
    full = formatting.voucher(VOUCHER)
    assert "organizationId" not in full
    assert full["version"] == 3
    assert full["voucherItems"][0]["categoryId"] == CATEGORY


def test_amounts_pass_through_untouched() -> None:
    """Accounting data. A helpfully rounded number is a wrong number."""
    odd = {**VOUCHER, "totalGrossAmount": 1234.567, "totalTaxAmount": 0.005}
    full = formatting.voucher(odd)
    assert full["totalGrossAmount"] == 1234.567
    assert full["totalTaxAmount"] == 0.005


def test_the_voucher_page_uses_the_shared_shape() -> None:
    result = formatting.vouchers_page(PAGE)
    assert list(result) == ["vouchers", "page"]
    assert result["page"]["totalElements"] == 1
    assert "nullHandling" not in str(result)


# -- payloads -------------------------------------------------------------


def test_the_totals_are_added_up_from_the_lines_for_a_gross_voucher() -> None:
    """With gross the line amounts already include the tax."""
    body = voucher_body(
        voucher_type="salesinvoice",
        tax_type="gross",
        items=[VoucherItem(**LINE)],
    )
    assert body["totalGrossAmount"] == 238.0
    assert body["totalTaxAmount"] == 38.0


def test_the_totals_add_the_tax_on_for_a_net_voucher() -> None:
    body = voucher_body(
        voucher_type="salesinvoice",
        tax_type="net",
        items=[VoucherItem(**{**LINE, "amount": 200.0})],
    )
    assert body["totalGrossAmount"] == 238.0
    assert body["totalTaxAmount"] == 38.0


def test_several_lines_are_summed() -> None:
    body = voucher_body(
        tax_type="gross",
        items=[
            VoucherItem(**LINE),
            VoucherItem(**{**LINE, "amount": 119.0, "tax_amount": 19.0}),
        ],
    )
    assert body["totalGrossAmount"] == 357.0
    assert body["totalTaxAmount"] == 57.0


def test_a_stated_total_is_sent_unchanged() -> None:
    """The API is the judge of whether it matches, not this code."""
    body = voucher_body(
        tax_type="gross", items=[VoucherItem(**LINE)], total_gross_amount=999.0
    )
    assert body["totalGrossAmount"] == 999.0


def test_a_named_contact_turns_off_the_collective_one() -> None:
    body = voucher_body(contact_id="PLACEHOLDER-CONTACT-1", tax_type="gross", items=[])
    assert body["contactId"] == "PLACEHOLDER-CONTACT-1"
    assert body["useCollectiveContact"] is False


def test_the_collective_contact_clears_a_named_one() -> None:
    body = voucher_body(base={**VOUCHER, "contactId": "x"}, use_collective_contact=True)
    assert "contactId" not in body
    assert body["useCollectiveContact"] is True


def test_an_update_does_not_echo_the_status_back() -> None:
    """Verified live: a PUT carrying voucherStatus is refused outright.

    Contacts accept their read-only fields and ignore them. Vouchers do not,
    and the offline suite would never have caught the difference.
    """
    body = voucher_body(base=VOUCHER, remark="changed")
    assert "voucherStatus" not in body
    assert "contactName" not in body
    assert "createdDate" not in body
    assert "organizationId" not in body


def test_an_update_keeps_the_lines_and_the_version() -> None:
    body = voucher_body(base=VOUCHER, remark="changed")
    assert body["voucherItems"] == VOUCHER["voucherItems"]
    assert body["version"] == 3
    assert body["voucherNumber"] == "MCP-0001"
    assert body["remark"] == "changed"


# -- tools ----------------------------------------------------------------


async def test_the_read_tools_are_listed_and_the_write_ones_are_not() -> None:
    names = [tool.name for tool in await build_server(Settings()).list_tools()]
    assert {"search_vouchers", "get_voucher", "get_payments"} <= set(names)
    assert "create_voucher" not in names
    assert "update_voucher" not in names


async def test_the_write_tools_appear_in_write_mode() -> None:
    names = [
        tool.name for tool in await build_server(Settings(mode="write")).list_tools()
    ]
    assert "create_voucher" in names
    assert "update_voucher" in names


async def test_the_search_description_says_it_is_the_way_in() -> None:
    server = build_server(Settings())
    tool = next(t for t in await server.list_tools() if t.name == "search_vouchers")
    assert tool.description is not None
    assert "search_contacts" in tool.description
    assert "one api call" in tool.description.lower()


async def test_the_default_search_asks_for_everything() -> None:
    handler = Scripted((200, PAGE))
    server, provider = server_for(handler)

    await server.call_tool("search_vouchers", {})

    assert handler.query["voucherType"] == ["any"]
    assert handler.query["voucherStatus"] == ["any"]
    assert handler.query["sort"] == ["voucherDate,DESC"]
    await provider.aclose()


async def test_get_voucher_refuses_both_ways_of_naming_one() -> None:
    handler = Scripted((200, VOUCHER))
    server, provider = server_for(handler)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(
            "get_voucher", {"voucher_id": "a", "voucher_number": "b"}
        )

    assert "not both" in str(excinfo.value)
    assert handler.requests == [], "a request went out anyway"
    await provider.aclose()


async def test_get_voucher_refuses_neither() -> None:
    handler = Scripted((200, VOUCHER))
    server, provider = server_for(handler)

    with pytest.raises(ToolError):
        await server.call_tool("get_voucher", {})

    assert handler.requests == []
    await provider.aclose()


async def test_a_number_that_matches_one_voucher_returns_it() -> None:
    handler = Scripted((200, {**PAGE, "content": [VOUCHER]}))
    server, provider = server_for(handler)

    result = await server.call_tool("get_voucher", {"voucher_number": "MCP-0001"})

    assert handler.query["voucherNumber"] == ["MCP-0001"]
    assert result.structured_content is not None
    assert result.structured_content["id"] == "PLACEHOLDER-VOUCHER-1"
    await provider.aclose()


async def test_get_voucher_by_id_reads_the_record_directly() -> None:
    handler = Scripted((200, VOUCHER))
    server, provider = server_for(handler)

    result = await server.call_tool(
        "get_voucher", {"voucher_id": "PLACEHOLDER-VOUCHER-1"}
    )

    assert handler.path == "/v1/vouchers/PLACEHOLDER-VOUCHER-1"
    assert result.structured_content is not None
    assert result.structured_content["voucherNumber"] == "MCP-0001"
    await provider.aclose()


async def test_get_payments_reports_what_is_still_outstanding() -> None:
    handler = Scripted((200, PAYMENTS))
    server, provider = server_for(handler)

    result = await server.call_tool(
        "get_payments", {"voucher_id": "PLACEHOLDER-VOUCHER-1"}
    )

    assert result.structured_content is not None
    assert result.structured_content["openAmount"] == 0.0
    assert handler.path == "/v1/payments/PLACEHOLDER-VOUCHER-1"
    await provider.aclose()


async def test_a_number_that_matches_nothing_is_a_not_found() -> None:
    handler = Scripted((200, {**PAGE, "content": [], "totalElements": 0}))
    server, provider = server_for(handler)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("get_voucher", {"voucher_number": "NOPE"})

    assert "NOPE" in str(excinfo.value)
    await provider.aclose()


async def test_an_ambiguous_number_names_the_candidates() -> None:
    """Numbers are unique by convention, not by constraint. Seen live."""
    second = {**VOUCHER, "id": "PLACEHOLDER-VOUCHER-2"}
    handler = Scripted((200, {**PAGE, "content": [VOUCHER, second]}))
    server, provider = server_for(handler)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("get_voucher", {"voucher_number": "MCP-0001"})

    message = str(excinfo.value)
    assert "PLACEHOLDER-VOUCHER-1" in message
    assert "PLACEHOLDER-VOUCHER-2" in message
    await provider.aclose()


async def test_create_voucher_sends_the_lines_and_the_computed_totals() -> None:
    handler = Scripted((201, WRITTEN))
    server, provider = server_for(handler, mode="write")

    await server.call_tool(
        "create_voucher",
        {
            "voucher_type": "salesinvoice",
            "voucher_date": "2026-08-19",
            "tax_type": "gross",
            "items": [LINE],
        },
    )

    body = handler.body(0)
    assert body["type"] == "salesinvoice"
    assert body["version"] == 0
    assert body["totalGrossAmount"] == 238.0
    assert body["voucherItems"][0]["categoryId"] == CATEGORY
    assert body["useCollectiveContact"] is True
    assert "voucherStatus" not in body
    await provider.aclose()


async def test_unchecked_records_it_for_review_instead_of_booking_it() -> None:
    handler = Scripted((201, WRITTEN))
    server, provider = server_for(handler, mode="write")

    await server.call_tool(
        "create_voucher",
        {
            "voucher_type": "salesinvoice",
            "voucher_date": "2026-08-19",
            "tax_type": "gross",
            "items": [LINE],
            "unchecked": True,
        },
    )

    assert handler.body(0)["voucherStatus"] == "unchecked"
    await provider.aclose()


async def test_a_create_is_never_retried() -> None:
    """A repeated create is a second booking of the same amount."""
    handler = Scripted((500, {}), (201, WRITTEN))
    server, provider = server_for(handler, mode="write")

    with pytest.raises(ToolError):
        await server.call_tool(
            "create_voucher",
            {
                "voucher_type": "salesinvoice",
                "voucher_date": "2026-08-19",
                "tax_type": "gross",
                "items": [LINE],
            },
        )

    assert len(handler.requests) == 1
    await provider.aclose()


async def test_update_voucher_reads_before_it_replaces() -> None:
    handler = Scripted((200, VOUCHER), (200, WRITTEN))
    server, provider = server_for(handler, mode="write")

    await server.call_tool(
        "update_voucher",
        {"voucher_id": "PLACEHOLDER-VOUCHER-1", "version": 3, "remark": "changed"},
    )

    assert handler.methods == ["GET", "PUT"]
    sent = handler.body(1)
    assert sent["remark"] == "changed"
    assert sent["voucherItems"] == VOUCHER["voucherItems"]
    assert "voucherStatus" not in sent
    await provider.aclose()


async def test_a_stale_version_stops_before_the_write() -> None:
    handler = Scripted((200, VOUCHER), (200, WRITTEN))
    server, provider = server_for(handler, mode="write")

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool(
            "update_voucher",
            {"voucher_id": "PLACEHOLDER-VOUCHER-1", "version": 1, "remark": "no"},
        )

    assert "version 3" in str(excinfo.value)
    assert handler.methods == ["GET"]
    await provider.aclose()
