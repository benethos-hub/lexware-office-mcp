"""The seven sales document types, and the templates that repeat them.

An invoice, a quotation, a credit note, an order confirmation, a delivery
note, a dunning and a down payment invoice are one shape with different
fields, and they live behind one path each rather than behind a type filter.
The type is therefore part of the address, not part of the query, which is
why every tool in this group takes it as an argument and why the mapping from
the name a caller uses to the path segment the API wants lives here.

The bookkeeping voucher these documents are often confused with is
:mod:`.vouchers`, and the rendered PDF is :mod:`.files`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .. import formatting
from ..client import ClientProvider
from ..config import Settings
from ..policy import classify
from ._base import PageNumber, PageSize, register_tool

__all__ = [
    "RESOURCES",
    "DocumentIdField",
    "DocumentType",
    "DocumentTypeField",
    "register",
]

# The seven types, and the path segment each one lives under. The segments
# are plural and kebab-cased, which is also what the web app's permalinks use.
DocumentType = Literal[
    "invoice",
    "quotation",
    "credit-note",
    "order-confirmation",
    "delivery-note",
    "dunning",
    "down-payment-invoice",
]

RESOURCES: dict[str, str] = {
    "invoice": "invoices",
    "quotation": "quotations",
    "credit-note": "credit-notes",
    "order-confirmation": "order-confirmations",
    "delivery-note": "delivery-notes",
    "dunning": "dunnings",
    "down-payment-invoice": "down-payment-invoices",
}

# Both fields are shared with `download_document` in :mod:`.files`, which
# addresses the same seven documents. One wording, sent to the model once per
# tool that uses it, rather than two that can drift apart.
DocumentTypeField = Annotated[
    DocumentType,
    Field(
        description=(
            "Which kind of document this is. Take it from the `voucherType` "
            "search_vouchers reported, where a sales invoice is 'invoice'."
        )
    ),
]

# Measured 2026-08-21 by sending `title`: the API names the four it takes.
RecurringSort = Literal[
    "createdDate,DESC",
    "createdDate,ASC",
    "updatedDate,DESC",
    "updatedDate,ASC",
    "nextExecutionDate,DESC",
    "nextExecutionDate,ASC",
    "lastExecutionDate,DESC",
    "lastExecutionDate,ASC",
]

DocumentIdField = Annotated[
    str,
    Field(description="The document's Lexware id, as returned by search_vouchers."),
]


def register(server: MCPServer, settings: Settings, provider: ClientProvider) -> None:
    """Register the sales document tools. The policy file decides the rest."""

    @classify("read", "sales_documents")
    async def get_sales_document(
        document_type: DocumentTypeField,
        document_id: DocumentIdField,
    ) -> dict[str, Any]:
        """Read one sales document in full: an invoice, quotation or their kin.

        One API call. Returns the recipient, the line items with their unit
        prices, the totals, the tax breakdown and the `version`.

        `document_type` has to match the id. A mismatch answers "not found",
        exactly as a wrong id does.

        A draft reads in full but carries no `files.documentFileId`: nothing
        has been rendered yet, and `download_document` refuses it.

        For a bookkeeping voucher use `get_voucher`.
        """
        payload = await provider.get().sales_document(
            RESOURCES[document_type], document_id
        )
        return formatting.sales_document(payload)

    @classify("read", "sales_documents")
    async def get_recurring_templates(
        template_id: Annotated[
            str | None,
            Field(
                description=(
                    "Read one template by id. Left unset, a page of them "
                    "comes back instead."
                )
            ),
        ] = None,
        sort: Annotated[
            RecurringSort | None,
            Field(
                description=(
                    "Which date to order by, newest first unless ',ASC' is "
                    "added. The API sorts on these four and nothing else."
                )
            ),
        ] = None,
        page: PageNumber = 0,
        size: PageSize = 25,
    ) -> dict[str, Any]:
        """Read the templates that issue invoices on a schedule.

        One API call. With `template_id` it answers with that one template,
        without it with a page of them.

        There is nothing to filter by: the API offers no search here, only
        paging and the sort. Reading a template is the whole of what the API
        allows - one cannot be created, changed or run from here.
        """
        client = provider.get()
        if template_id is not None:
            return formatting.recurring_template(
                await client.recurring_template(template_id)
            )
        return formatting.recurring_templates_page(
            await client.recurring_templates(page=page, size=size, sort=sort)
        )

    register_tool(server, get_sales_document)
    register_tool(server, get_recurring_templates)
