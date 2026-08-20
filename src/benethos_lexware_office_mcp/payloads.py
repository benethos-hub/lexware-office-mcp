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

__all__ = [
    "Address",
    "ContactKind",
    "Role",
    "TaxType",
    "VoucherItem",
    "VoucherType",
    "contact_body",
    "voucher_body",
]

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


VoucherType = Literal[
    "salesinvoice", "salescreditnote", "purchaseinvoice", "purchasecreditnote"
]
TaxType = Literal["net", "gross", "vatfree"]

# Fields a voucher carries when read but refuses when written back. Contacts
# accept their read-only fields and ignore them, vouchers do not: a PUT that
# echoes `voucherStatus` is refused outright with `voucherStatus:
# invalid_value`. Verified 2026-08-20, which is the only way this would have
# been found — the offline suite mocks the API and would have stayed green.
VOUCHER_PUT_DROP = (
    "voucherStatus",
    "contactName",
    "createdDate",
    "updatedDate",
    "organizationId",
)


class VoucherItem(BaseModel):
    """One line of a bookkeeping voucher.

    The API checks these against the voucher's totals and refuses a mismatch
    with ``totalGrossAmount: invalid_total_amount``. It also checks the tax
    against the tax type: with ``net`` the amount is net and a gross figure is
    refused as ``voucherItems[0].taxAmount: invalid_taxamount``. Verified
    2026-08-20.
    """

    amount: float = Field(
        description=(
            "The line amount. Gross when the voucher's tax_type is 'gross', "
            "net when it is 'net'."
        )
    )
    tax_amount: float = Field(
        description="The tax on this line. Zero for a vatfree voucher."
    )
    tax_rate_percent: float = Field(
        description="The tax rate as a percentage, for example 19."
    )
    category_id: str = Field(
        description=(
            "The posting category this line books to, from get_master_data "
            "with kind 'posting-categories'. Not a name, the category's id."
        )
    )


def voucher_body(
    *,
    base: dict[str, Any] | None = None,
    voucher_type: VoucherType | None = None,
    voucher_number: str | None = None,
    voucher_date: str | None = None,
    due_date: str | None = None,
    shipping_date: str | None = None,
    tax_type: TaxType | None = None,
    contact_id: str | None = None,
    use_collective_contact: bool | None = None,
    items: list[VoucherItem] | None = None,
    total_gross_amount: float | None = None,
    total_tax_amount: float | None = None,
    remark: str | None = None,
    voucher_status: str | None = None,
) -> dict[str, Any]:
    """Build the body for creating or updating a bookkeeping voucher.

    As with :func:`contact_body`, ``base`` turns this from a create into an
    update, because a PUT replaces the record rather than patching it.

    The totals are computed from the items when the caller does not state
    them. That is arithmetic, not invention: the API rejects totals that do
    not match the lines, and a caller who does state them has theirs sent
    unchanged and checked upstream.
    """
    body: dict[str, Any] = (
        {k: v for k, v in base.items() if k not in VOUCHER_PUT_DROP}
        if base
        else {"version": 0}
    )

    _set(body, "type", voucher_type)
    _set(body, "voucherNumber", voucher_number)
    _set(body, "voucherDate", voucher_date)
    _set(body, "dueDate", due_date)
    _set(body, "shippingDate", shipping_date)
    _set(body, "taxType", tax_type)
    _set(body, "remark", remark)
    _set(body, "voucherStatus", voucher_status)

    if contact_id is not None:
        body["contactId"] = contact_id
        body["useCollectiveContact"] = False
    elif use_collective_contact is not None:
        body["useCollectiveContact"] = use_collective_contact
        if use_collective_contact:
            body.pop("contactId", None)

    if items is not None:
        body["voucherItems"] = [_item_body(item) for item in items]

    lines = body.get("voucherItems") or []
    effective_tax_type = body.get("taxType")
    body["totalTaxAmount"] = (
        total_tax_amount if total_tax_amount is not None else _sum(lines, "taxAmount")
    )
    body["totalGrossAmount"] = (
        total_gross_amount
        if total_gross_amount is not None
        else _gross_total(lines, effective_tax_type)
    )
    return body


def _set(body: dict[str, Any], key: str, value: Any) -> None:
    """Assign only what the caller actually mentioned."""
    if value is not None:
        body[key] = value


def _item_body(item: VoucherItem) -> dict[str, Any]:
    return {
        "amount": item.amount,
        "taxAmount": item.tax_amount,
        "taxRatePercent": item.tax_rate_percent,
        "categoryId": item.category_id,
    }


def _sum(lines: list[dict[str, Any]], key: str) -> float:
    return round(sum(float(line.get(key) or 0) for line in lines), 2)


def _gross_total(lines: list[dict[str, Any]], tax_type: Any) -> float:
    """What the lines add up to including tax.

    With ``gross`` the line amounts already include it. With ``net`` and with
    ``vatfree`` they do not, and for vatfree the tax is zero anyway, so adding
    it is correct in both cases.
    """
    amounts = _sum(lines, "amount")
    if tax_type == "gross":
        return amounts
    return round(amounts + _sum(lines, "taxAmount"), 2)
