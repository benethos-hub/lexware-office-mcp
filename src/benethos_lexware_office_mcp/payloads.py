"""Tool arguments to API request bodies.

The mirror image of :mod:`formatting`, which turns API responses into tool
output. This module turns tool arguments into what the API expects, and it
exists as its own layer because the two directions are not symmetric: a
response is trimmed, a request has to be *complete*.

That asymmetry is the whole reason :func:`contact_body` takes a ``base``.
``PUT /v1/contacts/{id}`` replaces the record rather than patching it, so a
request carrying only the changed fields does not update a contact, it empties
everything else out of it. An update therefore starts from the record as it is
now and lays the changes on top. Verified against a live account on
2026-08-20, including that the read-only fields in a read-back record
(``organizationId``, the role numbers, ``archived``) are accepted and ignored
on the way back in.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

__all__ = ["Address", "ContactKind", "Role", "contact_body"]

ContactKind = Literal["company", "person"]
Role = Literal["customer", "vendor"]

# Which list an address or a number is filed under when the caller does not
# care. The API keeps one entry per kind, so the choice only decides the label.
_COMPANY_EMAIL = "business"
_PERSON_EMAIL = "private"
_COMPANY_PHONE = "business"
_PERSON_PHONE = "private"


class Address(BaseModel):
    """One postal address.

    A contact holds at most one billing and one shipping address, which the
    API enforces: a second entry is refused with
    ``addresses.billing.size: invalid_value``. Verified 2026-08-20.
    """

    street: str | None = Field(
        None, description="Street and house number, for example 'Musterweg 1'."
    )
    supplement: str | None = Field(
        None, description="Address line 2, for example 'Building C'."
    )
    zip: str | None = Field(None, description="Postal code.")
    city: str | None = Field(None, description="City.")
    country_code: str = Field(
        description=(
            "ISO 3166 alpha-2 country code, for example 'DE'. The API "
            "validates this and refuses anything else."
        ),
        min_length=2,
        max_length=2,
    )


def contact_body(
    *,
    base: dict[str, Any] | None = None,
    kind: ContactKind | None = None,
    name: str | None = None,
    first_name: str | None = None,
    salutation: str | None = None,
    roles: list[Role] | None = None,
    email: str | None = None,
    phone: str | None = None,
    billing_address: Address | None = None,
    shipping_address: Address | None = None,
    vat_registration_id: str | None = None,
    tax_number: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Build the body for creating or updating a contact.

    Without ``base`` this is a create: the result carries ``version: 0``,
    which is what the API expects for a new record. With ``base`` — a contact
    as ``GET`` just returned it — the given fields are laid on top and
    everything else is carried over unchanged, including the ``version`` that
    makes the update fail rather than overwrite if the record moved on.

    Anything left at ``None`` is not a change. Fields that hold a single value
    upstream are replaced rather than merged, because the API stores only one
    of each anyway.
    """
    body: dict[str, Any] = dict(base) if base else {"version": 0}
    is_company = _is_company(body, kind)

    if roles is not None:
        body["roles"] = _roles_body(body.get("roles"), roles)
    elif "roles" not in body:
        body["roles"] = {"customer": {}}

    _apply_identity(body, is_company, name, first_name, salutation)

    if is_company:
        company = dict(body.get("company") or {})
        if vat_registration_id is not None:
            company["vatRegistrationId"] = vat_registration_id
        if tax_number is not None:
            company["taxNumber"] = tax_number
        if company:
            body["company"] = company

    if email is not None:
        kind_key = _COMPANY_EMAIL if is_company else _PERSON_EMAIL
        body["emailAddresses"] = {
            **(body.get("emailAddresses") or {}),
            kind_key: [email],
        }
    if phone is not None:
        kind_key = _COMPANY_PHONE if is_company else _PERSON_PHONE
        body["phoneNumbers"] = {**(body.get("phoneNumbers") or {}), kind_key: [phone]}

    addresses = dict(body.get("addresses") or {})
    if billing_address is not None:
        addresses["billing"] = [_address_body(billing_address)]
    if shipping_address is not None:
        addresses["shipping"] = [_address_body(shipping_address)]
    if addresses:
        body["addresses"] = addresses

    if note is not None:
        body["note"] = note

    return body


def _is_company(body: dict[str, Any], kind: ContactKind | None) -> bool:
    """Whether this contact is a company.

    On an update the caller does not say, and must not have to: a contact
    cannot change from a company into a person, and the API refuses a record
    carrying both.
    """
    if kind is not None:
        return kind == "company"
    return "company" in body


def _apply_identity(
    body: dict[str, Any],
    is_company: bool,
    name: str | None,
    first_name: str | None,
    salutation: str | None,
) -> None:
    """Set the name, on whichever of the two blocks this contact uses."""
    if is_company:
        if name is not None:
            body["company"] = {**(body.get("company") or {}), "name": name}
        return

    person = dict(body.get("person") or {})
    if name is not None:
        person["lastName"] = name
    if first_name is not None:
        person["firstName"] = first_name
    if salutation is not None:
        person["salutation"] = salutation
    if person:
        body["person"] = person


def _roles_body(current: Any, roles: list[Role]) -> dict[str, Any]:
    """The roles block, keeping the numbers the API already assigned.

    A role that stays keeps its sub-object, so the customer number survives an
    update that only adds the vendor role. A role that is left out is dropped,
    which is how a role is removed.
    """
    existing = current if isinstance(current, dict) else {}
    return {role: existing.get(role) or {} for role in roles}


def _address_body(address: Address) -> dict[str, Any]:
    """One address in the API's own field names, without the empty lines."""
    fields = {
        "supplement": address.supplement,
        "street": address.street,
        "zip": address.zip,
        "city": address.city,
        "countryCode": address.country_code,
    }
    return {key: value for key, value in fields.items() if value is not None}
