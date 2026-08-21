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

from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp import formatting
from benethos_lexware_office_mcp.client import ClientProvider, LexwareClient
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.errors import NotFoundError
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import build_server
from benethos_lexware_office_mcp.tools.sales_documents import RESOURCES

API_KEY = "test-key-0123456789"

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


async def _no_sleep(_seconds: float) -> None:
    return None


class Scripted:
    """Answers a scripted sequence, and remembers what it was asked for."""

    def __init__(self, *responses: tuple[int, Any]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, payload = self._responses.pop(0) if self._responses else (200, {})
        return httpx.Response(status, json=payload)

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


async def test_the_document_is_read_from_its_own_path() -> None:
    handler = Scripted((200, INVOICE))
    async with make_client(handler) as client:
        await client.sales_document("invoices", "PLACEHOLDER-INVOICE-1")

    assert handler.path == "/v1/invoices/PLACEHOLDER-INVOICE-1"
    assert len(handler.requests) == 1, "one API call, as the description says"


async def test_a_missing_document_is_a_not_found() -> None:
    """A wrong type answers this too, which is why the tool names both."""
    handler = Scripted((404, {"message": "does not exist"}))
    async with make_client(handler) as client:
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
    server, provider = server_for(handler)

    result = await server.call_tool(
        "get_sales_document",
        {"document_type": "invoice", "document_id": "PLACEHOLDER-INVOICE-1"},
    )

    assert result.structured_content is not None
    assert result.structured_content["voucherNumber"] == "RE0001"
    assert result.structured_content["address"]["contactId"] == "PLACEHOLDER-CONTACT-1"
    await provider.aclose()


async def test_an_open_document_says_where_its_pdf_is() -> None:
    """`files.documentFileId` is what `download_file` would take."""
    handler = Scripted((200, INVOICE))
    server, provider = server_for(handler)

    result = await server.call_tool(
        "get_sales_document",
        {"document_type": "invoice", "document_id": "PLACEHOLDER-INVOICE-1"},
    )

    assert result.structured_content is not None
    assert result.structured_content["files"]["documentFileId"] == "PLACEHOLDER-FILE-1"
    await provider.aclose()


async def test_a_draft_reads_in_full_and_carries_no_document() -> None:
    """It cannot be downloaded, but every figure on it can be read."""
    handler = Scripted((200, DRAFT))
    server, provider = server_for(handler)

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
    server, provider = server_for(handler)

    await server.call_tool(
        "get_sales_document",
        {"document_type": document_type, "document_id": "PLACEHOLDER-DOC-1"},
    )

    assert handler.path == f"/v1/{segment}/PLACEHOLDER-DOC-1"
    await provider.aclose()


async def test_an_unknown_type_never_reaches_the_api() -> None:
    """The schema is a `Literal`, so the client can only send a real type."""
    handler = Scripted((200, INVOICE))
    server, provider = server_for(handler)

    with pytest.raises(ToolError):
        await server.call_tool(
            "get_sales_document",
            {"document_type": "receipt", "document_id": "PLACEHOLDER-DOC-1"},
        )

    assert handler.requests == []
    await provider.aclose()


async def test_the_document_types_are_the_ones_the_client_is_offered() -> None:
    handler = Scripted()
    server, provider = server_for(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    offered = tools["get_sales_document"].input_schema["properties"]["document_type"]

    assert set(offered["enum"]) == set(RESOURCES)
    await provider.aclose()


async def test_the_description_says_what_it_costs_and_what_a_draft_lacks() -> None:
    handler = Scripted()
    server, provider = server_for(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    description = tools["get_sales_document"].description or ""

    assert "one api call" in description.lower()
    assert "draft" in description.lower()
    assert len(description) < 700, "the description budget, see CLAUDE.md"
    await provider.aclose()
