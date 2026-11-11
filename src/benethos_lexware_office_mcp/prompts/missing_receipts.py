"""Which receipt or invoice a period lacks, read from the rhythm of the year before.

A supplier who bills every month, a customer invoiced every quarter: the
voucher list of the past twelve months shows the rhythm, and a period where
it breaks is where something was forgotten. The rules are fixed, so the same
books give the same answer every time. Unfinished vouchers of the period,
drafts and those not yet checked, are listed beside it, since they are the
other way a period stays open.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ._base import ENABLED, RULES, Prompt


class MissingReceipts(Prompt):
    name = "missing_receipts"
    title = "Missing receipts"

    def render(
        self,
        period: Annotated[
            str,
            Field(
                description="A month such as 2026-10, a quarter such as "
                "2026-Q3, or a year. The last complete month if left out."
            ),
        ] = "",
    ) -> str:
        """Which receipt or invoice a period lacks, by the rhythm of the year before."""
        return f"""Check the books for receipts and invoices missing in the \
period "{period}". It is a month such as 2026-10, a quarter such as 2026-Q3, \
or a year. When it is empty, take the last complete month before today.

{ENABLED}

1. Fix the first and the last day of the period. The history is the twelve \
months before its first day.
2. Call `search_vouchers` with date_from the first day of the history, \
date_to the last day of the period, sort voucherDate,ASC and size 250, and \
page through to the end. Leave out every row whose `voucherType` is \
quotation, orderconfirmation or deliverynote, and every row whose \
`voucherStatus` is voided.
3. Call `get_recurring_templates`. A contact with a template whose \
`executionStatus` says it still runs is invoiced on its schedule, which \
`recurringTemplateSettings` carries.

Work by these fixed rules, so that the same books always give the same \
answer.

- Groups. One group per `contactName` and direction. Incoming are \
purchaseinvoice and purchasecreditnote, outgoing every other type. A row \
without a contact name belongs to no group. When one group holds two amounts \
that recur side by side, two contracts with the same supplier for instance, \
split it by `totalAmount`, within ten percent.
- Rhythm, read from the history alone by `voucherDate`. Monthly: a voucher \
in at least four of the last six months of the history. Quarterly, when not \
monthly: a voucher in at least three of its last four quarters. Yearly, when \
neither: one voucher in the history, dated twelve months before a month of \
the period. One year is a single observation, so mark that rhythm as weak. \
Any other group has no rhythm and is not reported as missing.
- Expected. Monthly in every month of the period. Quarterly in each month of \
the period that lies a multiple of three months after the group's last \
voucher. Yearly in the month twelve months after it. A voucher dated in \
that month, or up to ten days either side of it, meets it.
- Not due yet. An expected month that has not ended by today is not missing, \
list it as not due yet.
- Ended. When the expected voucher is missing in the two months or quarters \
before the period as well, the rhythm has likely ended, a contract \
cancelled. List the group as possibly ended rather than missing.
- Templates. An outgoing group with a running template is expected as its \
schedule says. A missing invoice there means the template did not run, say \
so.
- Unfinished. Every row dated in the period with `voucherStatus` draft or \
unchecked is open still, whatever its rhythm.

Then report, in this order: what is missing, as a table with contact, \
direction, rhythm, the usual amount, the month expected, and the number and \
date of the last voucher with a link from `get_deeplink`, which costs no \
API call: the target is the document type for invoice (invoice), creditnote \
(credit-note) and downpaymentinvoice (down-payment-invoice), and voucher for \
the bookkeeping types. Then the unfinished vouchers of the period, with \
their links. Then the groups possibly ended, and those not due yet. Last, \
one line per group whose rhythm was met, so the person sees what was \
checked. A rhythm is a hint and not a fact: a missing voucher may never have \
been issued, so ask about it rather than asserting it is lost.

{RULES}"""
