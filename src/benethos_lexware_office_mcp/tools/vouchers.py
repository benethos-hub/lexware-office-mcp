"""The voucher list, bookkeeping vouchers and their payment status.

"Voucher" means three different things upstream, and the tools here follow
that split rather than papering over it:

- ``/v1/voucherlist`` is a read-only **index** over sales and bookkeeping
  documents alike. It is the only way to find anything without already
  knowing its id, which makes `search_vouchers` the entry point to almost
  every other tool.
- ``/v1/vouchers`` holds **bookkeeping vouchers**: a booked amount, a posting
  category, a tax rate. That is what `get_voucher` reads and what
  `create_voucher` writes.
- The sales documents themselves (invoices, quotations and their relatives)
  live behind their own paths and are a separate group.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from ..api.client import ClientProvider
from ..config import Settings
from ..errors import NotFoundError, ValidationError
from ..policy import classify
from ..records import formatting
from ..records.payloads import voucher_body
from ..records.types import (
    SearchStatus,
    SearchType,
    SortOrder,
    TaxType,
    VoucherItem,
    VoucherType,
)
from ._base import PageNumber, PageSize, register_tool, require_version

__all__ = ["register"]

VoucherId = Annotated[
    str,
    Field(
        description=(
            "The voucher's Lexware id, as returned by search_vouchers. Not "
            "the voucher number a human reads off the document."
        )
    ),
]

Items = Annotated[
    list[VoucherItem],
    Field(
        description=(
            "The lines this voucher books. Every line names the posting "
            "category it belongs to. At least one is required."
        ),
        min_length=1,
    ),
]


def register(server: MCPServer, settings: Settings, provider: ClientProvider) -> None:
    """Register the voucher tools. The policy file decides the rest."""

    @classify("read", "vouchers")
    async def search_vouchers(
        voucher_type: Annotated[
            SearchType,
            Field(
                description=(
                    "Which kind of document to look for. 'any' covers all of "
                    "them. 'invoice' means a sales document, 'salesinvoice' "
                    "and 'purchaseinvoice' are the bookkeeping records. "
                    "Dunnings cannot be found here at all."
                )
            ),
        ] = "any",
        voucher_status: Annotated[
            SearchStatus,
            Field(
                description=(
                    "Which state to look for. 'any' covers all of them. "
                    "'open' is unpaid, 'paid' is settled, 'draft' is not "
                    "finalized, 'voided' is cancelled."
                )
            ),
        ] = "any",
        contact_id: Annotated[
            str | None,
            Field(
                description=(
                    "Only documents for this contact, by id from search_contacts."
                )
            ),
        ] = None,
        voucher_number: Annotated[
            str | None,
            Field(
                description=(
                    "The document number, for example 'RE0001', matched in "
                    "full and ignoring case. Not a prefix."
                )
            ),
        ] = None,
        date_from: Annotated[
            str | None,
            Field(
                description=(
                    "Earliest voucher date, as YYYY-MM-DD. This is the date "
                    "on the document, not the date it was entered."
                )
            ),
        ] = None,
        date_to: Annotated[
            str | None, Field(description="Latest voucher date, as YYYY-MM-DD.")
        ] = None,
        only_overdue: Annotated[
            bool | None,
            Field(description="Only documents whose due date has passed unpaid."),
        ] = None,
        only_open: Annotated[
            bool | None, Field(description="Only documents with an amount outstanding.")
        ] = None,
        archived: Annotated[
            bool | None,
            Field(
                description=(
                    "Set true to look at archived documents, false for active "
                    "ones. Left unset, both are returned."
                )
            ),
        ] = None,
        sort: Annotated[
            SortOrder,
            Field(
                description=(
                    "Ordering. Newest voucher date first by default. "
                    "createdDate and updatedDate are when it was entered or "
                    "last changed."
                )
            ),
        ] = "voucherDate,DESC",
        page: PageNumber = 0,
        size: PageSize = settings.page_size,
    ) -> dict[str, Any]:
        """Find invoices, credit notes, quotations and bookkeeping vouchers.

        One API call per page. The only way to turn a question about the books
        into the ids `get_voucher`, `get_payments` and the document tools
        need. Starting from a customer name, get the contact id from
        `search_contacts` first and pass it here.

        Rows carry id, type, status, number, dates, contact name, total and
        open amount. A row marked `archived` is filed away.

        Narrow `voucher_type` and `voucher_status` to keep the answer small.
        `only_open` and `only_overdue` answer "what is still outstanding"
        without paging through everything.
        """
        payload = await provider.get().voucherlist(
            voucher_type=voucher_type,
            voucher_status=voucher_status,
            contact_id=contact_id,
            voucher_number=voucher_number,
            voucher_date_from=date_from,
            voucher_date_to=date_to,
            only_overdue=only_overdue,
            only_open=only_open,
            archived=archived,
            sort=sort,
            page=page,
            size=size,
        )
        return formatting.vouchers_page(payload)

    @classify("read", "vouchers")
    async def get_voucher(
        voucher_id: Annotated[
            str | None,
            Field(
                description=(
                    "The voucher's Lexware id, from search_vouchers. Give "
                    "this or voucher_number, not both."
                )
            ),
        ] = None,
        voucher_number: Annotated[
            str | None,
            Field(
                description=(
                    "The number printed on the document, for example "
                    "'RE-2026-014'. Use this when that is all you have."
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Read one bookkeeping voucher, by id or by its document number.

        One API call. Returns the booked amounts, tax type, the posting
        category of every line, the contact and the `version`.

        Prefer the id. A number is unique only by convention, and
        `search_vouchers` finds one across every document type.

        For whether it has been paid, use `get_payments` with the same id.
        """
        if (voucher_id is None) == (voucher_number is None):
            raise ValidationError(
                "Give either voucher_id or voucher_number, not both and not "
                "neither. Use search_vouchers to find a voucher when you have "
                "neither."
            )

        client = provider.get()
        if voucher_id is not None:
            return formatting.voucher(await client.voucher(voucher_id))

        found = await client.vouchers_by_number(voucher_number or "")
        matches = found.get("content") or []
        if not matches:
            raise NotFoundError("voucher carrying the number", voucher_number or "")
        if len(matches) > 1:
            ids = ", ".join(str(match.get("id")) for match in matches)
            raise ValidationError(
                f"{len(matches)} vouchers carry the number "
                f"{voucher_number!r}: {ids}. Read one of them by id."
            )
        return formatting.voucher(matches[0])

    @classify("read", "vouchers")
    async def get_payments(voucher_id: VoucherId) -> dict[str, Any]:
        """Show whether a voucher has been paid, and what is still open.

        Returns the payment status, the amount still outstanding, the currency
        and the individual payments recorded against it. Costs one API call.

        Takes the id of the **voucher**, not of a payment. An `openAmount` of
        0 is the answer to "is it settled" and is reported rather than
        omitted.
        """
        return formatting.payments(await provider.get().payments(voucher_id))

    @classify("write", "vouchers", "create", permanence="books")
    async def create_voucher(
        voucher_type: Annotated[
            VoucherType,
            Field(
                description=(
                    "What is being booked: a sales invoice or credit note is "
                    "money owed to the account, a purchase invoice or credit "
                    "note is money the account owes."
                )
            ),
        ],
        voucher_date: Annotated[
            str,
            Field(description="The date on the document, as YYYY-MM-DD."),
        ],
        tax_type: Annotated[
            TaxType,
            Field(
                description=(
                    "'gross' means the line amounts include tax, 'net' means "
                    "they do not, 'vatfree' means there is none. The API "
                    "checks the lines against this and refuses a mismatch."
                )
            ),
        ],
        items: Items,
        voucher_number: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The number on the document being recorded, for example "
                    "the supplier's invoice number. Required by the API for "
                    "every voucher type."
                ),
            ),
        ],
        contact_id: Annotated[
            str | None,
            Field(
                description=(
                    "The customer or vendor this belongs to, by id from "
                    "search_contacts. Leave unset to book against the "
                    "collective contact instead of a named one."
                )
            ),
        ] = None,
        due_date: Annotated[
            str | None, Field(description="When payment is due, as YYYY-MM-DD.")
        ] = None,
        shipping_date: Annotated[
            str | None,
            Field(description="Delivery or service date, as YYYY-MM-DD."),
        ] = None,
        total_gross_amount: Annotated[
            float | None,
            Field(
                description=(
                    "The total including tax. Leave unset to have it added up "
                    "from the lines, which is what the API expects it to "
                    "equal."
                )
            ),
        ] = None,
        total_tax_amount: Annotated[
            float | None,
            Field(description="The total tax. Also added up from the lines if unset."),
        ] = None,
        remark: Annotated[
            str | None, Field(description="A note kept with the voucher.")
        ] = None,
    ) -> dict[str, Any]:
        """Record a bookkeeping voucher in the account.

        Writes real accounting data, and **the API cannot take it back**:
        there is no way to delete a voucher here. Correcting one is a job for
        the web app. Confirm the organization with `get_profile` first. One
        API call, never retried.

        Every line needs a posting category **id**, from `get_master_data`
        with kind 'posting-categories'. Totals are added up from the lines
        unless stated. It is booked immediately and no status can be asked
        for. To record a receipt for review instead, use `upload_file`, which
        files it as an unchecked purchase invoice.
        """
        body = voucher_body(
            voucher_type=voucher_type,
            voucher_number=voucher_number,
            voucher_date=voucher_date,
            due_date=due_date,
            shipping_date=shipping_date,
            tax_type=tax_type,
            contact_id=contact_id,
            use_collective_contact=contact_id is None,
            items=items,
            total_gross_amount=total_gross_amount,
            total_tax_amount=total_tax_amount,
            remark=remark,
        )
        return formatting.compact_object(await provider.get().create_voucher(body))

    @classify("write", "vouchers", "update")
    async def update_voucher(
        voucher_id: VoucherId,
        version: Annotated[
            int,
            Field(
                description=(
                    "The `version` from the voucher as you last read it. If "
                    "it has changed since, the update is refused instead of "
                    "overwriting that change."
                ),
                ge=0,
            ),
        ],
        voucher_date: Annotated[
            str | None, Field(description="New document date, as YYYY-MM-DD.")
        ] = None,
        due_date: Annotated[
            str | None, Field(description="New due date, as YYYY-MM-DD.")
        ] = None,
        voucher_number: Annotated[
            str | None, Field(description="New document number.")
        ] = None,
        contact_id: Annotated[
            str | None, Field(description="Move it to a different contact, by id.")
        ] = None,
        use_collective_contact: Annotated[
            bool | None,
            Field(
                description=(
                    "True moves it to the collective contact instead of a "
                    "named one. Not together with contact_id."
                )
            ),
        ] = None,
        items: Annotated[
            list[VoucherItem] | None,
            Field(
                description=(
                    "Replaces every line on the voucher. The totals are "
                    "recomputed to match unless you state them."
                ),
                min_length=1,
            ),
        ] = None,
        total_gross_amount: Annotated[
            float | None, Field(description="New total including tax.")
        ] = None,
        total_tax_amount: Annotated[
            float | None, Field(description="New total tax.")
        ] = None,
        remark: Annotated[str | None, Field(description="New note.")] = None,
        finalize: Annotated[
            bool,
            Field(
                description=(
                    "Book an unchecked voucher, such as one upload_file made, "
                    "by moving it to open. Only when the user asked for that. "
                    "Needs confirm."
                )
            ),
        ] = False,
        confirm: Annotated[
            bool,
            Field(description="Required only for finalize. Ignored otherwise."),
        ] = False,
    ) -> dict[str, Any]:
        """Change a bookkeeping voucher that is already recorded.

        Writes real accounting data. Read it with `get_voucher` first: it
        shows what is there and carries the `version` this needs. Two API
        calls. Passing `items` **replaces** every line rather than adding one.

        An `unchecked` voucher takes new data and stays unchecked until
        `finalize` books it, which needs its number, date, contact and lines.

        If the voucher changed since that read, nothing is written. One that
        is already paid or booked may be refused whatever the version.
        """
        if finalize and not confirm:
            raise ValidationError(
                "finalize books the voucher and the API cannot take it back. "
                "Use it only when the user asked to book it, and pass "
                "confirm=true as well. Leaving finalize unset changes the "
                "voucher and leaves it unchecked."
            )
        if contact_id is not None and use_collective_contact:
            raise ValidationError(
                "Pass contact_id or use_collective_contact, not both: a voucher "
                "belongs either to a named contact or to the collective one."
            )
        client = provider.get()
        current = await client.voucher(voucher_id)
        require_version(current, version, noun="voucher", reader="get_voucher")
        status = current.get("voucherStatus")
        if finalize and status != "unchecked":
            raise ValidationError(
                f"finalize only books an unchecked voucher, and this one is "
                f"{status}. Nothing was written."
            )

        body = voucher_body(
            base=current,
            voucher_number=voucher_number,
            voucher_date=voucher_date,
            due_date=due_date,
            contact_id=contact_id,
            use_collective_contact=use_collective_contact,
            items=items,
            total_gross_amount=total_gross_amount,
            total_tax_amount=total_tax_amount,
            remark=remark,
            finalize=finalize,
        )
        return formatting.compact_object(await client.update_voucher(voucher_id, body))

    register_tool(server, search_vouchers)
    register_tool(server, get_voucher)
    register_tool(server, get_payments)
    register_tool(server, create_voucher)
    register_tool(server, update_voucher)
