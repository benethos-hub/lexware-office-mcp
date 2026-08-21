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
from ..errors import ValidationError
from ..payloads import (
    SHIPPING_REQUIRED,
    SalesLineItem,
    SalesTaxType,
    sales_document_body,
)
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
# A down payment invoice has no POST at all - it is raised by the app when a
# quotation is part-invoiced. Measured against the documented endpoint list
# and confirmed by the six that do accept one, 2026-08-21.
CreatableType = Literal[
    "invoice",
    "quotation",
    "credit-note",
    "order-confirmation",
    "delivery-note",
    "dunning",
]

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

        A row is shorter than the record behind it: what a template will
        actually invoice, its lines and tax, is only in the record, so read by
        id to see that.

        `recurringTemplateSettings` carries the schedule. `executionStatus`
        says whether it still runs, and `finalize` false means each run leaves
        a draft rather than issuing an invoice.

        There is nothing to filter by, and reading is all the API allows.
        """
        client = provider.get()
        if template_id is not None:
            return formatting.recurring_template(
                await client.recurring_template(template_id)
            )
        return formatting.recurring_templates_page(
            await client.recurring_templates(page=page, size=size, sort=sort)
        )

    @classify("write", "sales_documents", "create")
    async def create_sales_document(
        document_type: Annotated[
            CreatableType,
            Field(
                description=(
                    "What to create. A down payment invoice cannot be created "
                    "through the API at all."
                )
            ),
        ],
        contact_id: Annotated[
            str,
            Field(
                description=(
                    "Who the document is for, by id from search_contacts. A "
                    "one-time address is not supported: create the contact."
                )
            ),
        ],
        voucher_date: Annotated[
            str, Field(description="The date on the document, as YYYY-MM-DD.")
        ],
        items: Annotated[
            list[SalesLineItem],
            Field(description="The lines of the document.", min_length=1),
        ],
        tax_type: Annotated[
            SalesTaxType,
            Field(
                description=(
                    "Whether the line prices are before or after tax. "
                    "'vatfree' is for a document that carries none."
                )
            ),
        ] = "net",
        currency: Annotated[
            str, Field(description="ISO currency code.", min_length=3, max_length=3)
        ] = "EUR",
        shipping_date: Annotated[
            str | None,
            Field(
                description=(
                    "When it was delivered or performed, as YYYY-MM-DD. "
                    "Required for an invoice, order confirmation and delivery "
                    "note."
                )
            ),
        ] = None,
        expiration_date: Annotated[
            str | None,
            Field(
                description=(
                    "How long a quotation stands, as YYYY-MM-DD. Required for one."
                )
            ),
        ] = None,
        preceding_sales_voucher_id: Annotated[
            str | None,
            Field(
                description=(
                    "The finalized document this one follows, for example the "
                    "quotation an invoice comes from. Required for a dunning."
                )
            ),
        ] = None,
        title: Annotated[
            str | None,
            Field(description="Heading. The account's default is used if unset."),
        ] = None,
        introduction: Annotated[
            str | None, Field(description="Text above the lines.")
        ] = None,
        remark: Annotated[
            str | None, Field(description="Text below the lines.")
        ] = None,
        finalize: Annotated[
            bool,
            Field(
                description=(
                    "Issue it instead of drafting it. Needs confirm, and "
                    "cannot be reversed."
                )
            ),
        ] = False,
        confirm: Annotated[
            bool,
            Field(description="Required only for finalize. Ignored otherwise."),
        ] = False,
    ) -> dict[str, Any]:
        """Create an invoice, quotation, credit note or one of their relatives.

        Writes to the account. One API call, never retried, so a failure that
        might have gone through has to be checked with `search_vouchers`.

        A draft can still be edited or deleted in the web app. `finalize`
        issues it instead, assigning the number for good.
        That **cannot be undone**, so it needs `confirm` as well.

        Each kind wants one thing of its own: `shipping_date` for an invoice,
        order confirmation and delivery note, `expiration_date` for a
        quotation, `preceding_sales_voucher_id` for a dunning.

        Totals are added up by the API from the lines.
        """
        if finalize and not confirm:
            raise ValidationError(
                "finalize issues the document for good, and the API cannot "
                "take it back. Pass confirm=true as well, or leave finalize "
                "unset to create a draft that can still be changed."
            )
        if document_type in SHIPPING_REQUIRED and shipping_date is None:
            raise ValidationError(
                f"shipping_date is required for a document of type "
                f"'{document_type}': the day it was delivered or performed. "
                "The API refuses it otherwise."
            )
        if document_type == "quotation" and expiration_date is None:
            raise ValidationError(
                "A quotation needs expiration_date, the day it stops standing."
            )
        if document_type == "dunning" and preceding_sales_voucher_id is None:
            raise ValidationError(
                "A dunning follows an invoice. Pass its id as "
                "preceding_sales_voucher_id."
            )

        body = sales_document_body(
            contact_id=contact_id,
            voucher_date=voucher_date,
            items=items,
            tax_type=tax_type,
            currency=currency,
            shipping_date=shipping_date,
            expiration_date=expiration_date,
            title=title,
            introduction=introduction,
            remark=remark,
        )
        written = await provider.get().create_sales_document(
            RESOURCES[document_type],
            body,
            finalize=finalize,
            preceding_sales_voucher_id=preceding_sales_voucher_id,
        )
        return dict(formatting.compact(written))

    register_tool(server, get_sales_document)
    register_tool(server, create_sales_document)
    register_tool(server, get_recurring_templates)
