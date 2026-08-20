"""Contacts: customers and vendors, read and written."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .. import formatting
from ..client import ClientProvider
from ..config import Settings
from ..errors import ConflictError
from ..payloads import Address, ContactKind, Role, contact_body
from ..policy import requires, should_register
from ._base import PageNumber, PageSize, register_tool

__all__ = ["register"]

RoleFilter = Literal["customer", "vendor", "any"]

ContactId = Annotated[
    str,
    Field(
        description=(
            "The contact's Lexware id, as returned by search_contacts or "
            "referenced by a voucher."
        )
    ),
]

Roles = Annotated[
    list[Role],
    Field(
        description=(
            "What this contact is to the account: a customer, a vendor, or "
            "both. At least one is required. On an update this replaces the "
            "roles the contact has, so pass both to keep both."
        ),
        min_length=1,
    ),
]

Email = Annotated[
    str | None,
    Field(
        description=(
            "One email address. A contact holds at most one per category, so "
            "this replaces the existing one rather than adding to it."
        )
    ),
]

Phone = Annotated[
    str | None,
    Field(
        description=(
            "One phone number. As with the email address, this replaces "
            "rather than adds."
        )
    ),
]

Note = Annotated[
    str | None,
    Field(description="Free-text note on the contact, at most 1000 characters."),
]

BillingAddress = Annotated[
    Address | None,
    Field(description="The billing address. A contact has at most one."),
]

ShippingAddress = Annotated[
    Address | None,
    Field(description="The shipping address. A contact has at most one."),
]

VatId = Annotated[
    str | None,
    Field(
        description="VAT registration id, for example 'DE123456789'. Companies only."
    ),
]

TaxNumber = Annotated[
    str | None, Field(description="National tax number. Companies only.")
]


def register(server: MCPServer, settings: Settings, provider: ClientProvider) -> None:
    """Register the contact tools allowed at the active permission tier."""

    @requires("read")
    async def search_contacts(
        name: Annotated[
            str | None,
            Field(
                description=(
                    "Part of the contact's name, matched case-insensitively "
                    "against company names and person names. At least 3 "
                    "characters, the API rejects anything shorter."
                ),
                min_length=3,
                max_length=128,
            ),
        ] = None,
        email: Annotated[
            str | None,
            Field(
                description=(
                    "Part of any email address on the contact, matched "
                    "case-insensitively. At least 3 characters."
                ),
                min_length=3,
                max_length=128,
            ),
        ] = None,
        number: Annotated[
            int | None,
            Field(
                description=(
                    "The customer or vendor number a human uses for this "
                    "contact, for example 10001. This is not the contact id."
                ),
                ge=0,
            ),
        ] = None,
        role: Annotated[
            RoleFilter,
            Field(
                description=(
                    "Restrict to contacts that are customers, or that are "
                    "vendors. 'any' does not restrict."
                ),
            ),
        ] = "any",
        page: PageNumber = 0,
        size: PageSize = settings.page_size,
    ) -> dict[str, Any]:
        """Find contacts by name, email address, number or role.

        Costs one API call per page. Returns short rows carrying the contact
        id, the name, the customer and vendor numbers and one way to get in
        touch. Use `get_contact` afterwards for the full record with its
        addresses.

        This is how a name becomes an id. Any tool that takes a `contact_id`
        expects one from here, never a guessed or assembled value.

        All filters given are combined with AND, and leaving them all out
        lists the account's contacts in name order. Rows marked `archived` are
        no longer in active use, unmarked rows are active. Read `page` in the
        result to see whether more pages follow rather than paging blindly.
        """
        payload = await provider.get().contacts(
            name=name,
            email=email,
            number=number,
            customer=True if role == "customer" else None,
            vendor=True if role == "vendor" else None,
            page=page,
            size=size,
        )
        return formatting.contacts_page(payload)

    @requires("read")
    async def get_contact(contact_id: ContactId) -> dict[str, Any]:
        """Read one contact in full, by id.

        Returns the complete record: roles and their numbers, billing and
        shipping addresses, all email addresses and phone numbers, the note
        and the `version`. Costs one API call.

        Use `search_contacts` when you have a name rather than an id. Read
        this before updating a contact, because `update_contact` needs the
        `version` it reports.
        """
        return formatting.contact(await provider.get().contact(contact_id))

    @requires("write")
    async def create_contact(
        kind: Annotated[
            ContactKind,
            Field(
                description=(
                    "Whether this contact is a company or a private person. "
                    "A contact is one or the other and cannot be changed from "
                    "one into the other afterwards."
                )
            ),
        ],
        name: Annotated[
            str,
            Field(
                description=(
                    "The company name, or for a person the last name. Give "
                    "the first name separately."
                ),
                min_length=1,
            ),
        ],
        roles: Roles,
        first_name: Annotated[
            str | None, Field(description="First name. Persons only.")
        ] = None,
        salutation: Annotated[
            str | None,
            Field(description="Salutation such as 'Frau' or 'Herr'. Persons only."),
        ] = None,
        email: Email = None,
        phone: Phone = None,
        billing_address: BillingAddress = None,
        shipping_address: ShippingAddress = None,
        vat_registration_id: VatId = None,
        tax_number: TaxNumber = None,
        note: Note = None,
    ) -> dict[str, Any]:
        """Create a new customer or vendor in the account.

        Writes to real accounting data. Confirm with `get_profile` which
        organization is connected before calling this, and search for the name
        first: Lexware does not prevent a second contact with the same name,
        so a careless create leaves two records that later documents can be
        attached to at random.

        Returns the new contact's id and version, not the whole record, and
        costs one API call. The customer and vendor numbers are assigned by
        Lexware, so read the contact back if they are needed.

        The API requires a name and at least one role, and refuses a country
        code that is not ISO 3166 alpha-2.
        """
        body = contact_body(
            kind=kind,
            name=name,
            first_name=first_name,
            salutation=salutation,
            roles=roles,
            email=email,
            phone=phone,
            billing_address=billing_address,
            shipping_address=shipping_address,
            vat_registration_id=vat_registration_id,
            tax_number=tax_number,
            note=note,
        )
        return dict(formatting.compact(await provider.get().create_contact(body)))

    @requires("write")
    async def update_contact(
        contact_id: ContactId,
        version: Annotated[
            int,
            Field(
                description=(
                    "The `version` from the contact as you last read it. If "
                    "the record has changed since, the update is refused "
                    "instead of overwriting that change."
                ),
                ge=0,
            ),
        ],
        name: Annotated[
            str | None,
            Field(
                description="New company name, or for a person the last name.",
                min_length=1,
            ),
        ] = None,
        first_name: Annotated[
            str | None, Field(description="New first name. Persons only.")
        ] = None,
        salutation: Annotated[
            str | None, Field(description="New salutation. Persons only.")
        ] = None,
        roles: Annotated[
            list[Role] | None,
            Field(
                description=(
                    "Replaces the contact's roles. Leave unset to keep them. "
                    "Passing only one role removes the other."
                ),
                min_length=1,
            ),
        ] = None,
        email: Email = None,
        phone: Phone = None,
        billing_address: BillingAddress = None,
        shipping_address: ShippingAddress = None,
        vat_registration_id: VatId = None,
        tax_number: TaxNumber = None,
        note: Note = None,
    ) -> dict[str, Any]:
        """Change an existing contact. Only the fields you give are changed.

        Writes to real accounting data. Read the contact with `get_contact`
        first, both to see what is there and to get the `version` this tool
        needs.

        Costs two API calls: the API replaces the whole record rather than
        patching it, so the current one is read and the changes are laid on
        top. Without that, an update naming only a new email address would
        empty out the addresses, the note and everything else.

        If the contact changed between your read and this call, the update is
        refused and nothing is written. Read it again and decide what to do
        with the change you would have overwritten.
        """
        client = provider.get()
        current = await client.contact(contact_id)
        if current.get("version") != version:
            # Refused here rather than at the API, so nothing is sent at all.
            # The API would refuse it too, but its wording for this is
            # `version: invalid_value` behind a 406.
            raise ConflictError(
                f"This contact is at version {current.get('version')}, but the "
                f"update was written against version {version}. Somebody "
                "changed it in between. Read it again with get_contact, check "
                "whether your change still applies, then retry."
            )

        body = contact_body(
            base=current,
            name=name,
            first_name=first_name,
            salutation=salutation,
            roles=roles,
            email=email,
            phone=phone,
            billing_address=billing_address,
            shipping_address=shipping_address,
            vat_registration_id=vat_registration_id,
            tax_number=tax_number,
            note=note,
        )
        return dict(formatting.compact(await client.update_contact(contact_id, body)))

    if should_register("read", settings.mode):
        register_tool(server, search_contacts)
        register_tool(server, get_contact)
    if should_register("write", settings.mode):
        register_tool(server, create_contact)
        register_tool(server, update_contact)
