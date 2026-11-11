"""What is still unpaid, both ways: owed to the company and owed by it."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ._base import ENABLED, RULES, Prompt


class OpenItems(Prompt):
    name = "open_items"
    title = "Open items"

    def render(
        self,
        contact: Annotated[
            str,
            Field(
                description="A customer or vendor name, or part of one, to look "
                "at that contact only. Every contact if left out."
            ),
        ] = "",
    ) -> str:
        """What is still unpaid, owed to the company and owed by it, overdue first."""
        return f"""List what is still unpaid in the books. Contact filter: \
"{contact}". When the filter is empty, cover every contact.

{ENABLED}

1. When the contact filter is not empty, find the contact with \
`search_contacts` by name and take the `id` of the match. When several match, \
list them and ask which one is meant before going on. When none matches, say \
so and stop.
2. Call `search_vouchers` with voucher_status open and size 250, with the \
contact's id as contact_id when there is one. Open covers what is overdue as \
well. Leave out every row whose `voucherType` is quotation, \
orderconfirmation or deliverynote: an open quotation owes nothing.
3. Sort the rest by direction. invoice, salesinvoice and downpaymentinvoice \
are owed to the company, and creditnote and salescreditnote reduce that. \
purchaseinvoice is owed by the company, and purchasecreditnote reduces that.

Then report two tables, owed to the company and owed by it. Each has a row \
per contact with the number of documents, the sum of `openAmount` per \
currency, the earliest `dueDate` and how many days that lies before today. \
Contacts with something overdue come first, the longest overdue on top. A \
row without `openAmount` counts with its `totalAmount`, marked as such. Below \
each table, list the overdue documents one by one with number, date, due \
date and open amount, each with a link from `get_deeplink`, which costs no \
API call: the target is the document type for invoice (invoice), creditnote \
(credit-note) and downpaymentinvoice (down-payment-invoice), and voucher for \
the bookkeeping types.

{RULES}"""
