"""Templates that issue invoices on a schedule.

Both fixtures are what the live API returned on 2026-08-21, once a
Serienrechnung existed in the test account, with the ids replaced. The
difference between them is the point: **the API trims the list itself.** A row
carries nine fields, the record behind it twenty-one, and `lineItems`,
`version`, `taxConditions` and `voucherStatus` are only in the second. A
caller who needs to know what a template will invoice has to read it by id.

This is also where the drop-list approach earned itself: the shape guessed
before a live one existed had a `version` in the row, which the row does not
carry, and no `paymentConditions`, which it does. Passing everything but
`organizationId` through meant the tool was right anyway.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from benethos_lexware_office_mcp import formatting
from benethos_lexware_office_mcp.client import ClientProvider, LexwareClient
from benethos_lexware_office_mcp.config import Settings
from benethos_lexware_office_mcp.ratelimit import TokenBucket
from benethos_lexware_office_mcp.server import build_server

API_KEY = "test-key-0123456789"

# The schedule. `finalize` false is the setting that makes each run leave a
# draft rather than issuing and mailing an invoice, and `executionStatus`
# says whether it is still running at all.
SETTINGS: dict[str, Any] = {
    "id": "PLACEHOLDER-SETTINGS-1",
    "startDate": "2026-08-21",
    "finalize": False,
    "shippingType": "delivery",
    "retroactiveInvoice": False,
    "executionInterval": "MONTHLY",
    "nextExecutionDate": "2026-09-21",
    "lastExecutionDate": "2026-08-21",
    "lastExecutionFailed": False,
    "executionStatus": "ACTIVE",
}

# What a row of the list carries. Nine fields, and the API decides that, not
# this project.
ROW: dict[str, Any] = {
    "id": "PLACEHOLDER-TEMPLATE-1",
    "organizationId": "PLACEHOLDER-ORG-ID",
    "title": "Rechnung",
    "createdDate": "2026-08-21T20:28:07.442+02:00",
    "updatedDate": "2026-08-21T20:28:07.442+02:00",
    "address": {"contactId": "PLACEHOLDER-CONTACT-1", "name": "Testa Musterperson"},
    "totalPrice": {
        "currency": "EUR",
        "totalNetAmount": 123.0,
        "totalGrossAmount": 146.37,
    },
    "paymentConditions": {
        "paymentTermLabel": "Zahlbar sofort, rein netto",
        "paymentTermLabelTemplate": "Zahlbar sofort, rein netto",
        "paymentTermDuration": 0,
    },
    "recurringTemplateSettings": SETTINGS,
}

# And what reading one by id adds: the lines it will invoice, the version, the
# tax conditions, and the status of the document it produces.
TEMPLATE: dict[str, Any] = {
    **ROW,
    "version": 1,
    "voucherStatus": "draft",
    "language": "de",
    "archived": False,
    "electronicDocumentProfile": "NONE",
    "printLayoutId": "PLACEHOLDER-LAYOUT-1",
    "lineItems": [
        {
            "id": "PLACEHOLDER-ARTICLE-1",
            "type": "material",
            "name": "Ein Artikel",
            "quantity": 1,
            "unitName": "Stueck",
            "unitPrice": {
                "currency": "EUR",
                "netAmount": 123,
                "grossAmount": 146.37,
                "taxRatePercentage": 19,
            },
            "discountPercentage": 0,
            "lineItemAmount": 123.0,
        }
    ],
    "taxAmounts": [{"taxRatePercentage": 19.0, "taxAmount": 23.37, "netAmount": 123.0}],
    "taxConditions": {"taxType": "net"},
    "relatedVouchers": [],
    "introduction": (
        "Unsere Lieferungen/Leistungen stellen wir Ihnen wie folgt in Rechnung."
    ),
    "remark": "Vielen Dank fuer die gute Zusammenarbeit.",
}

PAGE: dict[str, Any] = {
    "content": [ROW],
    "first": True,
    "last": True,
    "number": 0,
    "numberOfElements": 1,
    "size": 25,
    "sort": [{"property": "updatedDate", "direction": "DESC"}],
    "totalElements": 1,
    "totalPages": 1,
}


async def _no_sleep(_seconds: float) -> None:
    return None


class Scripted:
    def __init__(self, *responses: tuple[int, Any]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, payload = self._responses.pop(0) if self._responses else (200, {})
        return httpx.Response(status, json=payload)

    @property
    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(str(self.requests[-1].url)).query)

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


async def test_the_page_is_asked_for_by_paging_alone() -> None:
    handler = Scripted((200, PAGE))
    async with make_client(handler) as client:
        await client.recurring_templates(page=1, size=50)

    assert handler.path == "/v1/recurring-templates"
    assert handler.query == {"page": ["1"], "size": ["50"]}


async def test_a_sort_is_passed_through_and_omitted_when_unset() -> None:
    handler = Scripted((200, PAGE), (200, PAGE))
    async with make_client(handler) as client:
        await client.recurring_templates(sort="nextExecutionDate,ASC")
        assert handler.query["sort"] == ["nextExecutionDate,ASC"]
        await client.recurring_templates()
        assert "sort" not in handler.query


async def test_one_template_is_read_from_its_own_path() -> None:
    handler = Scripted((200, TEMPLATE))
    async with make_client(handler) as client:
        await client.recurring_template("PLACEHOLDER-TEMPLATE-1")

    assert handler.path == "/v1/recurring-templates/PLACEHOLDER-TEMPLATE-1"


# -- formatting -----------------------------------------------------------


def test_only_the_organization_is_dropped() -> None:
    """Everything else the API sends is passed through, row or record alike."""
    formatted = formatting.recurring_template(TEMPLATE)

    assert "organizationId" not in formatted
    assert formatted["recurringTemplateSettings"]["executionInterval"] == "MONTHLY"
    assert formatted["version"] == 1


def test_the_schedule_survives_whole() -> None:
    """It is the only part of the record that is not an ordinary invoice, so
    losing a field of it would lose the point of the template."""
    settings = formatting.recurring_template(TEMPLATE)["recurringTemplateSettings"]

    assert settings["nextExecutionDate"] == "2026-09-21"
    assert settings["executionStatus"] == "ACTIVE"
    assert settings["finalize"] is False, "false means each run leaves a draft"
    assert settings["lastExecutionFailed"] is False, "a false that carries meaning"


def test_the_list_is_shorter_than_the_record_and_stays_that_way() -> None:
    """The API trims the row, not this project. Measured 2026-08-21: nine
    fields in a row against twenty-one in the record behind it."""
    row = formatting.recurring_templates_page(PAGE)["templates"][0]
    record = formatting.recurring_template(TEMPLATE)

    for absent in ("lineItems", "version", "taxConditions", "voucherStatus"):
        assert absent not in row, f"a row never carried {absent}"
        assert absent in record
    assert row["recurringTemplateSettings"]["executionStatus"] == "ACTIVE"


def test_an_unseen_field_survives() -> None:
    formatted = formatting.recurring_template({**TEMPLATE, "invented": "kept"})

    assert formatted["invented"] == "kept"


def test_the_page_uses_the_shared_envelope() -> None:
    formatted = formatting.recurring_templates_page(PAGE)

    assert formatted["page"]["totalElements"] == 1
    assert formatted["templates"][0]["id"] == "PLACEHOLDER-TEMPLATE-1"


def test_a_row_keeps_what_a_caller_chooses_by() -> None:
    """Nine fields is little enough that every one of them has to survive."""
    row = formatting.recurring_templates_page(PAGE)["templates"][0]

    assert row["title"] == "Rechnung"
    assert row["address"]["name"] == "Testa Musterperson"
    assert row["totalPrice"]["totalGrossAmount"] == 146.37
    assert row["paymentConditions"]["paymentTermDuration"] == 0


# -- the tool -------------------------------------------------------------


async def test_without_an_id_a_page_comes_back() -> None:
    handler = Scripted((200, PAGE))
    server, provider = server_for(handler)

    result = await server.call_tool("get_recurring_templates", {})

    assert result.structured_content is not None
    assert result.structured_content["page"]["totalElements"] == 1
    assert handler.path == "/v1/recurring-templates"
    await provider.aclose()


async def test_with_an_id_that_one_template_comes_back() -> None:
    handler = Scripted((200, TEMPLATE))
    server, provider = server_for(handler)

    result = await server.call_tool(
        "get_recurring_templates", {"template_id": "PLACEHOLDER-TEMPLATE-1"}
    )

    assert result.structured_content is not None
    assert result.structured_content["version"] == 1
    assert handler.path == "/v1/recurring-templates/PLACEHOLDER-TEMPLATE-1"
    await provider.aclose()


async def test_a_sort_the_api_refuses_never_leaves_the_server() -> None:
    """Measured 2026-08-21: `title` comes back as "must be one of" four dates,
    so the schema offers those four and nothing else."""
    handler = Scripted((200, PAGE))
    server, provider = server_for(handler)

    with pytest.raises(ToolError):
        await server.call_tool("get_recurring_templates", {"sort": "title,ASC"})

    assert handler.requests == []
    await provider.aclose()


async def test_the_description_says_reading_is_all_there_is() -> None:
    handler = Scripted()
    server, provider = server_for(handler)

    tools = {tool.name: tool for tool in await server.list_tools()}
    description = tools["get_recurring_templates"].description or ""

    assert "one api call" in description.lower()
    assert len(description) < 700, "the description budget, see CLAUDE.md"
    await provider.aclose()
