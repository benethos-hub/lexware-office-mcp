"""Reading a sales document, and the seven paths one can live behind.

The two fixtures are the shapes the live API returned on 2026-08-21 for the
first real invoice in the test account, once finalized and once as a draft,
with placeholder identifiers. The differences between them are not cosmetic:
an open document carries `dueDate`, `printLayoutId` and the `files` block
naming its rendered PDF, and a draft carries none of the three. Several
assertions below exist to keep that visible in the answer, because it is what
tells a caller whether there is anything to download.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp.errors import NotFoundError
from benethos_lexware_office_mcp.records import formatting
from benethos_lexware_office_mcp.records.types import RESOURCES
from helpers import Scripted, fast_client, server_with

INVOICE: dict[str, Any] = {
    "id": "PLACEHOLDER-INVOICE-1",
    "organizationId": "PLACEHOLDER-ORG-ID",
    "createdDate": "2026-08-21T13:31:04.795+02:00",
    "updatedDate": "2026-08-21T13:31:16.635+02:00",
    "version": 3,
    "language": "de",
    "archived": False,
    "voucherStatus": "open",
    "voucherNumber": "RE0001",
    "voucherDate": "2026-08-21T00:00:00.000+02:00",
    "dueDate": "2026-08-21T00:00:00.000+02:00",
    "address": {
        "contactId": "PLACEHOLDER-CONTACT-1",
        "name": "Testa Musterperson",
        "street": "Teststrasse 1",
        "city": "Berlin",
        "zip": "10115",
        "countryCode": "DE",
    },
    "electronicDocumentProfile": "NONE",
    "lineItems": [
        {
            "type": "custom",
            "name": "A line",
            "quantity": 1,
            "unitName": "Stueck",
            "unitPrice": {
                "currency": "EUR",
                "netAmount": 43,
                "grossAmount": 51.17,
                "taxRatePercentage": 19,
            },
            "discountPercentage": 0,
            "lineItemAmount": 43.0,
        }
    ],
    "totalPrice": {
        "currency": "EUR",
        "totalNetAmount": 43.0,
        "totalGrossAmount": 51.17,
        "totalTaxAmount": 8.17,
    },
    "taxAmounts": [{"taxRatePercentage": 19.0, "taxAmount": 8.17, "netAmount": 43.0}],
    "taxConditions": {"taxType": "net"},
    "shippingConditions": {
        "shippingDate": "2026-08-21T00:00:00.000+02:00",
        "shippingType": "delivery",
    },
    "closingInvoice": False,
    "relatedVouchers": [],
    "printLayoutId": "PLACEHOLDER-LAYOUT-1",
    "files": {"documentFileId": "PLACEHOLDER-FILE-1"},
    "title": "Rechnung",
}

DRAFT: dict[str, Any] = {
    key: value
    for key, value in INVOICE.items()
    if key not in ("dueDate", "printLayoutId", "files")
} | {"voucherStatus": "draft", "voucherNumber": "RE0002", "version": 1}


# -- client ---------------------------------------------------------------


async def test_the_document_is_read_from_its_own_path() -> None:
    handler = Scripted((200, INVOICE))
    async with fast_client(handler) as client:
        await client.sales_document("invoices", "PLACEHOLDER-INVOICE-1")

    assert handler.path == "/v1/invoices/PLACEHOLDER-INVOICE-1"
    assert len(handler.requests) == 1, "one API call, as the description says"


async def test_a_missing_document_is_a_not_found() -> None:
    """A wrong type answers this too, which is why the tool names both."""
    handler = Scripted((404, {"message": "does not exist"}))
    async with fast_client(handler) as client:
        with pytest.raises(NotFoundError):
            await client.sales_document("quotations", "PLACEHOLDER-INVOICE-1")


# -- formatting -----------------------------------------------------------


def test_the_organization_id_is_dropped() -> None:
    """Identical on every record, and `get_profile` already answers it."""
    assert "organizationId" not in formatting.sales_document(INVOICE)


def test_the_amounts_are_not_touched() -> None:
    formatted = formatting.sales_document(INVOICE)

    assert formatted["totalPrice"] == INVOICE["totalPrice"]
    assert formatted["lineItems"][0]["unitPrice"]["grossAmount"] == 51.17
    assert formatted["taxAmounts"][0]["taxAmount"] == 8.17


def test_a_zero_discount_survives_but_an_empty_list_does_not() -> None:
    formatted = formatting.sales_document(INVOICE)

    assert formatted["lineItems"][0]["discountPercentage"] == 0
    assert "relatedVouchers" not in formatted


def test_nothing_type_specific_is_filtered_out() -> None:
    """A drop-list, so a field this project has never seen still arrives."""
    formatted = formatting.sales_document({**INVOICE, "invented": "kept"})

    assert formatted["invented"] == "kept"
    assert formatted["title"] == "Rechnung"
    assert formatted["closingInvoice"] is False


# -- the tool -------------------------------------------------------------


async def test_reading_an_invoice_returns_it_whole() -> None:
    handler = Scripted((200, INVOICE))
    server, provider = server_with(handler)

    result = await server.call_tool(
        "get_sales_document",
        {"document_type": "invoice", "document_id": "PLACEHOLDER-INVOICE-1"},
    )

    assert result.structured_content is not None
    assert result.structured_content["voucherNumber"] == "RE0001"
    assert result.structured_content["address"]["contactId"] == "PLACEHOLDER-CONTACT-1"
    await provider.aclose()


async def test_an_open_document_passes_its_files_block_through() -> None:
    """Deprecated upstream for every sales document type, and passed through
    unchanged for as long as the API still sends it."""
    handler = Scripted((200, INVOICE))
    server, provider = server_with(handler)

    result = await server.call_tool(
        "get_sales_document",
        {"document_type": "invoice", "document_id": "PLACEHOLDER-INVOICE-1"},
    )

    assert result.structured_content is not None
    assert result.structured_content["files"]["documentFileId"] == "PLACEHOLDER-FILE-1"
    await provider.aclose()


async def test_the_description_names_the_status_not_the_deprecated_block() -> None:
    """`files.documentFileId` is going away on every type, so a model told to
    read a draft off its absence would be told something that stops being
    true. `voucherStatus` stays."""
    server, provider = server_with(Scripted())

    tools = {tool.name: tool for tool in await server.list_tools()}
    description = tools["get_sales_document"].description or ""

    assert "voucherStatus" in description
    assert "documentFileId" not in description
    await provider.aclose()


async def test_a_draft_reads_in_full_and_carries_no_document() -> None:
    """It cannot be downloaded, but every figure on it can be read."""
    handler = Scripted((200, DRAFT))
    server, provider = server_with(handler)

    result = await server.call_tool(
        "get_sales_document",
        {"document_type": "invoice", "document_id": "PLACEHOLDER-INVOICE-2"},
    )

    assert result.structured_content is not None
    assert result.structured_content["voucherStatus"] == "draft"
    assert result.structured_content["voucherNumber"] == "RE0002"
    assert result.structured_content["totalPrice"]["totalGrossAmount"] == 51.17
    assert "files" not in result.structured_content
    assert "dueDate" not in result.structured_content
    await provider.aclose()


@pytest.mark.parametrize(("document_type", "segment"), sorted(RESOURCES.items()))
async def test_every_type_reaches_its_own_path(
    document_type: str, segment: str
) -> None:
    handler = Scripted((200, INVOICE))
    server, provider = server_with(handler)

    await server.call_tool(
        "get_sales_document",
        {"document_type": document_type, "document_id": "PLACEHOLDER-DOC-1"},
    )

    assert handler.path == f"/v1/{segment}/PLACEHOLDER-DOC-1"
    await provider.aclose()


async def test_an_unknown_type_never_reaches_the_api() -> None:
    """The schema is a `Literal`, so the client can only send a real type."""
    handler = Scripted((200, INVOICE))
    server, provider = server_with(handler)

    with pytest.raises(ToolError):
        await server.call_tool(
            "get_sales_document",
            {"document_type": "receipt", "document_id": "PLACEHOLDER-DOC-1"},
        )

    assert handler.requests == []
    await provider.aclose()


async def test_the_document_types_are_the_ones_the_client_is_offered() -> None:
    handler = Scripted()
    server, provider = server_with(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    offered = tools["get_sales_document"].input_schema["properties"]["document_type"]

    assert set(offered["enum"]) == set(RESOURCES)
    await provider.aclose()


async def test_the_description_says_what_it_costs_and_what_a_draft_lacks() -> None:
    handler = Scripted()
    server, provider = server_with(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    description = tools["get_sales_document"].description or ""

    assert "one api call" in description.lower()
    assert "draft" in description.lower()
    assert len(description) < 700, "the description budget, see CLAUDE.md"
    await provider.aclose()


# -- creating one ---------------------------------------------------------

LINE = {
    "name": "Beratung",
    "quantity": 2,
    "unit_name": "Stunde",
    "unit_price": 90.0,
    "tax_rate_percent": 19,
}

CREATED = {
    "id": "PLACEHOLDER-INVOICE-3",
    "resourceUri": "https://api.lexware.io/v1/invoices/PLACEHOLDER-INVOICE-3",
    "createdDate": "2026-08-21T18:00:00.000+02:00",
    "updatedDate": "2026-08-21T18:00:00.000+02:00",
    "version": 1,
}


def _create_args(**extra: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "document_type": "invoice",
        "contact_id": "PLACEHOLDER-CONTACT-1",
        "voucher_date": "2026-08-21",
        "shipping_date": "2026-08-21",
        "items": [LINE],
    }
    args.update(extra)
    return args


async def test_a_draft_carries_the_lines_and_leaves_the_totals_to_the_api() -> None:
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)

    result = await server.call_tool("create_sales_document", _create_args())

    body = json.loads(handler.requests[0].content)
    assert handler.requests[0].method == "POST"
    assert handler.path == "/v1/invoices"
    assert body["address"] == {"contactId": "PLACEHOLDER-CONTACT-1"}
    assert body["totalPrice"] == {"currency": "EUR"}, "the API adds it up itself"
    assert body["lineItems"][0]["unitPrice"] == {
        "currency": "EUR",
        "netAmount": 90.0,
        "taxRatePercentage": 19,
    }
    assert result.structured_content is not None
    assert result.structured_content["id"] == "PLACEHOLDER-INVOICE-3"
    await provider.aclose()


async def test_a_plain_date_becomes_the_timestamp_the_api_insists_on() -> None:
    """Measured 2026-08-21: milliseconds and an offset are both mandatory here,
    where `/v1/vouchers` takes a bare date."""
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)

    await server.call_tool("create_sales_document", _create_args())

    body = json.loads(handler.requests[0].content)
    assert body["voucherDate"] == "2026-08-21T00:00:00.000Z"
    assert body["shippingConditions"]["shippingDate"] == "2026-08-21T00:00:00.000Z"
    await provider.aclose()


async def test_a_full_timestamp_is_left_alone() -> None:
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)

    await server.call_tool(
        "create_sales_document",
        _create_args(voucher_date="2026-08-21T09:30:00.000+02:00"),
    )

    body = json.loads(handler.requests[0].content)
    assert body["voucherDate"] == "2026-08-21T09:30:00.000+02:00"
    await provider.aclose()


async def test_a_gross_document_puts_the_price_on_the_gross_side() -> None:
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)

    await server.call_tool("create_sales_document", _create_args(tax_type="gross"))

    body = json.loads(handler.requests[0].content)
    assert body["taxConditions"] == {"taxType": "gross"}
    assert "grossAmount" in body["lineItems"][0]["unitPrice"]
    assert "netAmount" not in body["lineItems"][0]["unitPrice"]
    await provider.aclose()


async def test_a_line_may_quote_an_article_or_carry_no_price_at_all() -> None:
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)

    await server.call_tool(
        "create_sales_document",
        _create_args(
            items=[
                {**LINE, "item_type": "service", "article_id": "PLACEHOLDER-ARTICLE-1"},
                {**LINE, "item_type": "text", "name": "A note"},
            ]
        ),
    )

    lines = json.loads(handler.requests[0].content)["lineItems"]
    assert lines[0]["type"] == "service"
    assert lines[0]["id"] == "PLACEHOLDER-ARTICLE-1"
    assert lines[1] == {"type": "text", "name": "A note"}, "a text line has no price"
    await provider.aclose()


async def test_a_text_line_needs_nothing_but_its_text() -> None:
    """No quantity, unit, price or tax rate, which the schema used to demand."""
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)

    await server.call_tool(
        "create_sales_document",
        _create_args(items=[LINE, {"name": "A note", "item_type": "text"}]),
    )

    lines = json.loads(handler.requests[0].content)["lineItems"]
    assert lines[1] == {"type": "text", "name": "A note"}
    await provider.aclose()


async def test_a_priced_line_without_its_price_never_reaches_the_api() -> None:
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)
    unpriced = {key: value for key, value in LINE.items() if key != "unit_price"}

    with pytest.raises(ToolError, match="unit_price"):
        await server.call_tool("create_sales_document", _create_args(items=[unpriced]))

    assert handler.requests == []
    await provider.aclose()


@pytest.mark.parametrize(
    ("document_type", "missing"),
    [
        ("invoice", "shipping_date"),
        ("order-confirmation", "shipping_date"),
        ("delivery-note", "shipping_date"),
        ("quotation", "expiration_date"),
        ("dunning", "preceding_sales_voucher_id"),
    ],
)
async def test_what_each_kind_insists_on_is_refused_before_the_request(
    document_type: str, missing: str
) -> None:
    """Measured 2026-08-21 by posting a minimal body to each of them."""
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)
    args = _create_args(document_type=document_type)
    args.pop("shipping_date")

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("create_sales_document", args)

    assert missing in str(excinfo.value)
    assert handler.requests == [], "a request went out anyway"
    await provider.aclose()


async def test_a_credit_note_needs_nothing_of_its_own() -> None:
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)
    args = _create_args(document_type="credit-note")
    args.pop("shipping_date")

    await server.call_tool("create_sales_document", args)

    assert handler.path == "/v1/credit-notes"
    await provider.aclose()


async def test_finalizing_without_a_confirmation_never_reaches_the_api() -> None:
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)

    with pytest.raises(ToolError) as excinfo:
        await server.call_tool("create_sales_document", _create_args(finalize=True))

    assert "confirm" in str(excinfo.value)
    assert handler.requests == []
    await provider.aclose()


async def test_a_confirmed_finalize_becomes_a_query_parameter() -> None:
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)

    await server.call_tool(
        "create_sales_document", _create_args(finalize=True, confirm=True)
    )

    assert handler.query["finalize"] == ["true"]
    await provider.aclose()


async def test_a_draft_sends_no_finalize_at_all() -> None:
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)

    await server.call_tool("create_sales_document", _create_args(confirm=True))

    assert handler.query == {}
    await provider.aclose()


async def test_pursuing_a_document_names_it_in_the_query() -> None:
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)

    await server.call_tool(
        "create_sales_document",
        _create_args(preceding_sales_voucher_id="PLACEHOLDER-QUOTATION-1"),
    )

    assert handler.query["precedingSalesVoucherId"] == ["PLACEHOLDER-QUOTATION-1"]
    await provider.aclose()


async def test_a_creation_is_never_retried() -> None:
    """A repeat is a second document, and the API cannot delete either."""
    handler = Scripted((500, {}))
    server, provider = server_with(handler)

    with pytest.raises(ToolError):
        await server.call_tool("create_sales_document", _create_args())

    assert len(handler.requests) == 1
    await provider.aclose()


async def test_a_down_payment_invoice_cannot_be_created() -> None:
    """It has no POST at all - the app raises one from a part-invoiced
    quotation - so the schema does not offer it."""
    handler = Scripted((201, CREATED))
    server, provider = server_with(handler)

    with pytest.raises(ToolError):
        await server.call_tool(
            "create_sales_document", _create_args(document_type="down-payment-invoice")
        )

    assert handler.requests == []
    await provider.aclose()


async def test_the_creating_description_says_finalize_is_the_users_call() -> None:
    """Issuing a document is a decision, not a way of being helpful.

    The description is the only place a model reads this before it acts, so
    the rule has to be there rather than only in the repository's docs.
    """
    handler = Scripted()
    server, provider = server_with(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    description = tools["create_sales_document"].description or ""

    assert "only" in description.lower()
    assert "user asked" in description.lower()
    assert "cannot take that back" in description.lower()
    assert "draft" in description.lower()
    assert len(description) < 700, "the description budget, see CLAUDE.md"
    await provider.aclose()


async def test_the_finalize_parameter_repeats_the_rule_where_it_is_set() -> None:
    """A model reads the parameter, not only the prose above it."""
    handler = Scripted()
    server, provider = server_with(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    schema = tools["create_sales_document"].input_schema

    assert "asked for that" in schema["properties"]["finalize"]["description"]
    await provider.aclose()


async def test_the_voucher_list_spelling_of_a_type_is_taken_too() -> None:
    """The description says to copy `voucherType`, which spells four of the
    seven types without hyphens. Copying it was refused by the schema."""
    handler = Scripted((200, INVOICE))
    server, provider = server_with(handler)

    await server.call_tool(
        "get_sales_document",
        {"document_type": "orderconfirmation", "document_id": "PLACEHOLDER-DOC-1"},
    )

    assert handler.path == "/v1/order-confirmations/PLACEHOLDER-DOC-1"
    await provider.aclose()
