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

from typing import Any

from ..errors import ValidationError
from .types import (
    Address,
    ArticleType,
    ContactKind,
    LeadingPrice,
    Role,
    SalesLineItem,
    TaxType,
    VoucherItem,
    VoucherType,
)

__all__ = [
    "article_body",
    "contact_body",
    "require_type_fields",
    "sales_document_body",
    "voucher_body",
]

# Which list an address or a number is filed under when the caller does not
# care. The API keeps one entry per kind, so the choice only decides the label.
_COMPANY_EMAIL = "business"
_PERSON_EMAIL = "private"
_COMPANY_PHONE = "business"
_PERSON_PHONE = "private"


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

    Anything left at ``None`` is not a change. An email address or a phone
    number replaces every one the contact has rather than joining them, which
    is what the tool promises.
    """
    body: dict[str, Any] = dict(base) if base else {"version": 0}
    is_company = _is_company(body, kind)
    _refuse_misplaced(
        is_company,
        first_name=first_name,
        salutation=salutation,
        vat_registration_id=vat_registration_id,
        tax_number=tax_number,
    )

    if roles is not None:
        body["roles"] = _roles_body(body.get("roles"), roles)
    elif "roles" not in body:
        body["roles"] = {"customer": {}}

    _apply_identity(body, is_company, name, first_name, salutation)
    if is_company:
        _apply_tax_ids(body, vat_registration_id, tax_number)
    _apply_reachability(body, is_company, email, phone)
    _apply_addresses(body, billing_address, shipping_address)
    if note is not None:
        body["note"] = note
    return body


def _apply_tax_ids(
    body: dict[str, Any], vat_registration_id: str | None, tax_number: str | None
) -> None:
    """Set a company's VAT id and tax number, keeping what else it holds."""
    company = dict(body.get("company") or {})
    if vat_registration_id is not None:
        company["vatRegistrationId"] = vat_registration_id
    if tax_number is not None:
        company["taxNumber"] = tax_number
    if company:
        body["company"] = company


def _apply_reachability(
    body: dict[str, Any], is_company: bool, email: str | None, phone: str | None
) -> None:
    """Replace the email address and the phone number, each where it is given."""
    if email is not None:
        default = _COMPANY_EMAIL if is_company else _PERSON_EMAIL
        body["emailAddresses"] = {_kind(body.get("emailAddresses"), default): [email]}
    if phone is not None:
        default = _COMPANY_PHONE if is_company else _PERSON_PHONE
        body["phoneNumbers"] = {_kind(body.get("phoneNumbers"), default): [phone]}


def _apply_addresses(
    body: dict[str, Any], billing: Address | None, shipping: Address | None
) -> None:
    """Replace the billing and the shipping address, each where it is given."""
    addresses = dict(body.get("addresses") or {})
    if billing is not None:
        addresses["billing"] = [_address_body(billing)]
    if shipping is not None:
        addresses["shipping"] = [_address_body(shipping)]
    if addresses:
        body["addresses"] = addresses


def _kind(current: Any, default: str) -> str:
    """The category a replacing email address or phone number is filed under.

    The one the contact already uses when it uses exactly one, so an address
    kept under ``office`` stays there. Otherwise the default for this kind of
    contact. Either way the value replaces the whole block: merged into it, a
    new address under ``business`` sat beside the old one under ``office``,
    and the contact had two. Measured 2026-09-27.
    """
    used = [key for key, value in (current or {}).items() if value]
    return used[0] if len(used) == 1 else default


def _refuse_misplaced(is_company: bool, **given: str | None) -> None:
    """Refuse a field this kind of contact has no place for.

    A person carries a first name and a salutation, a company a VAT id and
    a tax number, and neither block takes the other's. Such a field used to
    be left out of the body, so the write reported success and stored
    nothing of it.
    """
    elsewhere = (
        ("first_name", "salutation")
        if is_company
        else ("vat_registration_id", "tax_number")
    )
    misplaced = [name for name in elsewhere if given.get(name) is not None]
    if misplaced:
        kind, other = ("company", "person") if is_company else ("person", "company")
        raise ValidationError(
            f"{', '.join(misplaced)} belongs to a {other}, and this contact is a "
            f"{kind}. Leave it out."
        )


def _is_company(body: dict[str, Any], kind: ContactKind | None) -> bool:
    """Whether this contact is a company.

    On an update the caller does not say, and must not have to: a contact
    cannot change from a company into a person, and the API refuses a record
    carrying both.

    Read off the block's content, not off the key: a person read back from
    the API has no ``company`` key at all (measured 2026-09-27), but a record
    that carries one as ``null`` beside a ``person`` block is still a person.
    """
    if kind is not None:
        return kind == "company"
    return bool(body.get("company")) and not body.get("person")


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


# Fields a voucher carries when read but refuses when written back. Contacts
# accept their read-only fields and ignore them, vouchers do not: a PUT that
# echoes `voucherStatus` is refused with `voucherStatus: invalid_value` for
# every status but `open`, which books an unchecked voucher and is sent only
# for `finalize`. Verified 2026-08-20 and, for the one exception, 2026-09-27 -
# the offline suite mocks the API and would have stayed green either way.
VOUCHER_PUT_DROP = (
    "voucherStatus",
    "contactName",
    "createdDate",
    "updatedDate",
    "organizationId",
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
    finalize: bool = False,
) -> dict[str, Any]:
    """Build the body for creating or updating a bookkeeping voucher.

    As with :func:`contact_body`, ``base`` turns this from a create into an
    update, because a PUT replaces the record rather than patching it.

    The totals are computed from the items when the caller does not state
    them. That is arithmetic, not invention: the API rejects totals that do
    not match the lines, and a caller who does state them has theirs sent
    unchanged and checked upstream. An update that leaves the lines and the
    tax type alone sends the totals it read back, untouched - a voucher made
    from an upload holds no lines, and adding up nothing gave it zero.

    **No ``voucherStatus`` is sent, with one exception.** A POST carrying one
    is refused with ``voucherStatus: invalid_value``, measured on 2026-08-23
    across three voucher types, and :data:`VOUCHER_PUT_DROP` strips the one
    in the record being merged. The exception is ``finalize``: a PUT
    carrying ``open`` is the one status change the API allows, turning an
    ``unchecked`` voucher into a booked one. Measured 2026-09-27: ``open`` is
    accepted, ``unchecked`` and ``paid`` are refused with ``invalid_value``,
    and without ``open`` an unchecked voucher takes the new data and stays
    unchecked.
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
    if finalize:
        body["voucherStatus"] = "open"

    if contact_id is not None:
        body["contactId"] = contact_id
        body["useCollectiveContact"] = False
    elif use_collective_contact is not None:
        body["useCollectiveContact"] = use_collective_contact
        if use_collective_contact:
            body.pop("contactId", None)

    if items is not None:
        body["voucherItems"] = [_item_body(item) for item in items]

    # Totals are derived only for lines this call wrote, or for a tax type
    # that changes what the lines mean. An update that touches neither keeps
    # the totals the API holds rather than a figure worked out here.
    derive = base is None or items is not None or tax_type is not None
    lines = body.get("voucherItems") or []
    if total_tax_amount is not None:
        body["totalTaxAmount"] = total_tax_amount
    elif derive:
        body["totalTaxAmount"] = _sum(lines, "taxAmount")
    if total_gross_amount is not None:
        body["totalGrossAmount"] = total_gross_amount
    elif derive:
        body["totalGrossAmount"] = _gross_total(lines, body.get("taxType"))
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


# -- articles -------------------------------------------------------------

# Computed by the API from the other half and the tax rate, and refused on
# the way back in only if it contradicts them. Sending the read-back value
# unchanged is what an update does, so it stays.
_PRICE_KEYS = ("leadingPrice", "netPrice", "grossPrice", "taxRate")


def article_body(
    *,
    base: dict[str, Any] | None = None,
    title: str | None = None,
    article_type: ArticleType | None = None,
    unit_name: str | None = None,
    price: float | None = None,
    leading_price: LeadingPrice | None = None,
    tax_rate: float | None = None,
    article_number: str | None = None,
    gtin: str | None = None,
    description: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Build the body for creating or updating an article.

    As with :func:`contact_body`, ``base`` turns this from a create into an
    update, because a PUT replaces the record rather than patching it.

    The price is one number and a side. The API stores both a net and a gross
    price and computes the one that was not given, so ``leading_price`` says
    which of the two the caller means and the other is left to the API rather
    than worked out here - an amount this project derived and sent would be a
    number nobody checked. Verified 2026-08-21: a gross price of 11.90 at 19%
    comes back with a net price of 10.00 beside it.
    """
    body: dict[str, Any] = dict(base) if base else {}
    for key in ("id", "organizationId", "createdDate", "updatedDate"):
        body.pop(key, None)
    if base is None:
        body["version"] = 0

    _set(body, "title", title)
    _set(body, "type", article_type)
    _set(body, "unitName", unit_name)
    _set(body, "articleNumber", article_number)
    _set(body, "gtin", gtin)
    _set(body, "description", description)
    _set(body, "note", note)

    current = dict(body.get("price") or {})
    side = leading_price or current.get("leadingPrice") or "NET"
    if price is not None or leading_price is not None or tax_rate is not None:
        # Only the leading side goes back, so the API computes the other one
        # instead of being handed a figure the new price or rate made stale.
        # The API would ignore that figure too - measured 2026-09-27, a new
        # rate beside both old prices recomputes the other side either way -
        # but a body that contradicts itself should not depend on that.
        leading = "netPrice" if side == "NET" else "grossPrice"
        kept = price if price is not None else current.get(leading)
        current.pop("netPrice", None)
        current.pop("grossPrice", None)
        _set(current, leading, kept)
        current["leadingPrice"] = side
        _set(current, "taxRate", tax_rate)
    if current:
        body["price"] = {k: v for k, v in current.items() if k in _PRICE_KEYS}
    return body


# -- sales documents ------------------------------------------------------

# Which extra field each type insists on, measured 2026-08-21 by posting a
# minimal body to each of them and reading what came back. A credit note
# wants nothing beyond the common fields.
SHIPPING_REQUIRED = ("invoice", "order-confirmation", "delivery-note")


def require_type_fields(
    document_type: str,
    *,
    shipping_date: str | None,
    expiration_date: str | None,
    preceding_sales_voucher_id: str | None,
) -> None:
    """Refuse a sales document missing the field its type insists on.

    Beside the table it reads, so that what each type needs is said in one
    place. Checked before the one POST a create gets, which the API would
    otherwise spend on the refusal.
    """
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
            "A dunning follows an invoice. Pass its id as preceding_sales_voucher_id."
        )


def _line_item_body(
    item: SalesLineItem, tax_type: str, currency: str
) -> dict[str, Any]:
    """One line, with the price on the side the document's tax type names.

    An ``article_id`` on any line but ``material`` or ``service`` is refused
    here. Measured 2026-10-08 on a ``custom`` line: the API answers 406,
    "Only line items of type 'material' or 'service' can contain an ID", so
    sending it spends the one POST on a refusal.
    """
    if item.article_id is not None and item.item_type not in ("material", "service"):
        raise ValidationError(
            f"The line {item.name!r} is '{item.item_type}' and carries "
            "article_id, which only a 'material' or 'service' line can. Make "
            "it one of those to quote the article, or leave article_id out."
        )
    if item.item_type == "text":
        body: dict[str, Any] = {"type": "text", "name": item.name}
        _set(body, "description", item.description)
        return body

    missing = [
        name
        for name in ("quantity", "unit_name", "unit_price", "tax_rate_percent")
        if getattr(item, name) is None
    ]
    if missing:
        raise ValidationError(
            f"The line {item.name!r} needs {', '.join(missing)}. Only a 'text' "
            "line goes without them."
        )

    amount_key = "grossAmount" if tax_type == "gross" else "netAmount"
    body = {
        "type": item.item_type,
        "name": item.name,
        "quantity": item.quantity,
        "unitName": item.unit_name,
        "unitPrice": {
            "currency": currency,
            amount_key: item.unit_price,
            "taxRatePercentage": item.tax_rate_percent,
        },
    }
    _set(body, "id", item.article_id)
    _set(body, "description", item.description)
    _set(body, "discountPercentage", item.discount_percentage)
    return body


def _at_midnight(value: str) -> str:
    """A plain date as the timestamp these endpoints insist on.

    Measured 2026-08-21: `/v1/invoices` accepts only
    ``yyyy-MM-dd'T'HH:mm:ss.SSSXXX``. The milliseconds are not optional and
    neither is the offset - ``2026-08-21``, ``...T00:00:00`` and
    ``...T00:00:00Z`` are all refused as unparseable, where ``/v1/vouchers``
    takes a bare date happily.

    Midnight **UTC** is used rather than a local offset this server cannot
    know. For an account in Germany that is 01:00 or 02:00 on the same
    calendar day, which is the day that matters. A caller who needs another
    zone passes a full timestamp, which goes through untouched.
    """
    return value if "T" in value else f"{value}T00:00:00.000Z"


def sales_document_body(
    *,
    contact_id: str,
    voucher_date: str,
    items: list[SalesLineItem],
    tax_type: TaxType = "net",
    currency: str = "EUR",
    shipping_date: str | None = None,
    expiration_date: str | None = None,
    title: str | None = None,
    introduction: str | None = None,
    remark: str | None = None,
) -> dict[str, Any]:
    """Build the body for creating a sales document.

    There is no ``base`` here, unlike the other builders: the API offers no
    PUT for these, so a document is written once and afterwards only read.

    ``totalPrice`` carries the currency and nothing else. The API adds the
    document up from its lines and refuses a total that disagrees, so stating
    one here would be a figure this project invented.
    """
    body: dict[str, Any] = {
        "voucherDate": _at_midnight(voucher_date),
        "address": {"contactId": contact_id},
        "lineItems": [_line_item_body(item, tax_type, currency) for item in items],
        "totalPrice": {"currency": currency},
        "taxConditions": {"taxType": tax_type},
    }
    if shipping_date is not None:
        body["shippingConditions"] = {
            "shippingDate": _at_midnight(shipping_date),
            # The one shipping type a document with a shipping date needs,
            # and the only one the tool offers.
            "shippingType": "delivery",
        }
    if expiration_date is not None:
        body["expirationDate"] = _at_midnight(expiration_date)
    _set(body, "title", title)
    _set(body, "introduction", introduction)
    _set(body, "remark", remark)
    return body
