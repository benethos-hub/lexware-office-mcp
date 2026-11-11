"""One customer or vendor at a glance: the record, the documents, what is open."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ._base import ENABLED, RULES, Prompt


class ContactOverview(Prompt):
    name = "contact_overview"
    title = "Contact overview"

    def render(
        self,
        contact: Annotated[
            str,
            Field(
                description="The customer or vendor: a name or part of one, or "
                "the customer or vendor number."
            ),
        ],
    ) -> str:
        """One customer or vendor: the record, the latest documents, what is open."""
        return f"""Give an overview of the contact "{contact}".

{ENABLED}

1. Find the contact with `search_contacts`: by number when the contact is \
given as digits only, by name otherwise. When several match, list them and \
ask which one is meant before going on. When none matches, say so and stop.
2. Call `get_contact` with its `id`.
3. Call `search_vouchers` with the id as contact_id and size 25, for the \
latest documents, newest first.
4. Call `search_vouchers` with the id as contact_id and voucher_status open, \
since an open document may be older than the latest ones.
5. Call `get_deeplink` with target contact for a link to the contact, which \
costs no API call.

Then report who the contact is, their roles with the customer and vendor \
numbers, and the address. Then what is open, owed to the company and owed \
by it, as a sum of `openAmount` per currency, with the overdue documents by \
number and due date. Leave out quotations, order confirmations and delivery \
notes there, which owe nothing. Then the latest documents as a table with \
type, number, date, status and total. End with the link.

{RULES}"""
