"""Contacts: customers and vendors."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .. import formatting
from ..client import ClientProvider
from ..config import MAX_PAGE_SIZE, Settings
from ..policy import requires, should_register
from ._base import register_tool

__all__ = ["register"]

Role = Literal["customer", "vendor", "any"]


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
            Role,
            Field(
                description=(
                    "Restrict to contacts that are customers, or that are "
                    "vendors. 'any' does not restrict."
                ),
            ),
        ] = "any",
        page: Annotated[int, Field(description="Zero-based page number.", ge=0)] = 0,
        size: Annotated[
            int,
            Field(description="Contacts per page.", ge=1, le=MAX_PAGE_SIZE),
        ] = settings.page_size,
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
    async def get_contact(
        contact_id: Annotated[
            str,
            Field(
                description=(
                    "The contact's Lexware id, as returned by search_contacts "
                    "or referenced by a voucher."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """Read one contact in full, by id.

        Returns the complete record: roles and their numbers, billing and
        shipping addresses, all email addresses and phone numbers, the note
        and the `version`. Costs one API call.

        Use `search_contacts` when you have a name rather than an id. Read
        this before updating a contact, because an update has to send back the
        `version` it read.
        """
        return formatting.contact(await provider.get().contact(contact_id))

    if should_register("read", settings.mode):
        register_tool(server, search_contacts)
        register_tool(server, get_contact)
