"""API JSON to compact tool output.

The client's token budget is a real constraint, so every response is trimmed
before it leaves. Two rules matter more than brevity:

- **Monetary values pass through untouched.** Never rounded, never
  reformatted, and never separated from their currency. This is accounting
  data, and a helpfully tidied number is a wrong number.
- **Zero and false survive.** Only ``None`` and empty containers are dropped.
  An open amount of ``0`` is the answer to "is it paid", not noise.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = [
    "article",
    "recurring_template",
    "recurring_templates_page",
    "article_row",
    "articles_page",
    "compact",
    "contact",
    "contacts_page",
    "master_data",
    "page",
    "page_info",
    "payments",
    "profile",
    "sales_document",
    "voucher",
    "vouchers_page",
]


def compact(value: Any) -> Any:
    """Drop nulls and empty containers, recursively.

    ``0``, ``0.0`` and ``False`` are kept on purpose: they carry meaning in
    accounting data. Only ``None``, ``""``, ``[]`` and ``{}`` go.
    """
    if isinstance(value, dict):
        cleaned = {k: compact(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if not _is_empty(v)}
    if isinstance(value, list):
        items = [compact(v) for v in value]
        return [v for v in items if not _is_empty(v)]
    return value


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str | list | dict | tuple):
        return len(value) == 0
    return False


# Every list endpoint answers with the same envelope. Of its nine fields these
# five are what a caller needs to decide whether to ask for another page.
# `first` restates `number == 0`, `numberOfElements` restates the row count,
# and `sort` describes the ordering with five fields per sort key and is
# identical on every response, so all three are dropped.
PAGE_KEYS = ("number", "size", "totalElements", "totalPages", "last")


def page_info(payload: dict[str, Any]) -> dict[str, Any]:
    """The paging part of a list response, trimmed."""
    return dict(compact({key: payload.get(key) for key in PAGE_KEYS}))


def page(
    payload: dict[str, Any],
    row: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    key: str,
) -> dict[str, Any]:
    """A list response as ``{<key>: [rows], "page": {...}}``.

    Shared by every paged endpoint so the shape stays the same across tools: a
    caller that has learned to page through one list can page through all of
    them. Only ``row`` differs, because only the records differ.
    """
    rows = [row(item) for item in payload.get("content") or []]
    return {key: rows, "page": page_info(payload)}


# `created` carries `userEmail` and `userName`, which are the address of the
# person who set the account up. The tool answers *which organization* is
# connected, so that person's identity is neither needed nor ours to hand to a
# language model. Dropped rather than compacted. Confirmed against a live
# account on 2026-08-20.
PROFILE_DROP = ("created",)


def profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize ``GET /v1/profile``.

    Keeps every field the API returns except the ones in
    :data:`PROFILE_DROP`, so a field added upstream shows up rather than being
    silently discarded by an allow-list.
    """
    kept = {k: v for k, v in payload.items() if k not in PROFILE_DROP}
    return dict(compact(kept))


# The same organization id sits on every record the account returns, and
# `get_profile` already answers which organization is connected. Repeating it
# on every contact buys the caller nothing and is paid for on every call.
CONTACT_DROP = ("organizationId",)

# Order of preference when picking the one address or number worth putting in
# a search result. Business before private, because a search result is a
# business record.
_EMAIL_KINDS = ("business", "office", "private", "other")
_PHONE_KINDS = ("business", "office", "mobile", "private", "fax", "other")


def contact(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one contact from ``GET /v1/contacts/{id}``.

    A drop-list rather than an allow-list, so a field Lexware adds upstream
    shows up instead of being silently swallowed. ``version`` is kept: an
    update has to send back the version it read.
    """
    kept = {k: v for k, v in payload.items() if k not in CONTACT_DROP}
    return dict(compact(kept))


def contacts_page(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a page of ``GET /v1/contacts`` into rows plus page info."""
    return page(payload, contact_row, key="contacts")


def contact_row(item: dict[str, Any]) -> dict[str, Any]:
    """One line of a contact search result.

    Identity, the numbers a human uses to refer to the record, and one way to
    reach it. Everything else is what ``get_contact`` is for.

    ``archived`` appears only when it is true. It is false on nearly every row
    and repeating it costs more than it tells anyone, which is why the tool
    description states that an unmarked row is active.
    """
    roles = item.get("roles") or {}
    company = item.get("company") or {}
    person = item.get("person") or {}

    row: dict[str, Any] = {
        "id": item.get("id"),
        "version": item.get("version"),
        "name": _contact_name(company, person),
        "type": "company" if company else ("person" if person else None),
        "roles": [name for name in ("customer", "vendor") if name in roles],
        "customerNumber": (roles.get("customer") or {}).get("number"),
        "vendorNumber": (roles.get("vendor") or {}).get("number"),
        "email": _first_entry(item.get("emailAddresses"), _EMAIL_KINDS),
        "phone": _first_entry(item.get("phoneNumbers"), _PHONE_KINDS),
    }
    if item.get("archived"):
        row["archived"] = True
    return dict(compact(row))


def _contact_name(company: dict[str, Any], person: dict[str, Any]) -> str:
    """The name a person would use for this contact.

    A contact is either a company or a person upstream. The salutation is
    deliberately left out: it identifies nobody and is paid for on every row.
    """
    if company.get("name"):
        return str(company["name"])
    parts = [person.get("firstName"), person.get("lastName")]
    return " ".join(str(part) for part in parts if part)


def _first_entry(block: Any, kinds: tuple[str, ...]) -> str | None:
    """The first value in ``block`` following the preference in ``kinds``.

    The API groups addresses and numbers by kind, each a list. A search result
    has room for one, so the kinds are tried in order rather than merged.
    """
    if not isinstance(block, dict):
        return None
    for kind in kinds:
        values = block.get(kind)
        if isinstance(values, list) and values:
            return str(values[0])
    return None


# The voucher list is the discovery tool, so its rows carry what a caller
# needs to choose one: what it is, what state it is in, who it is for, what it
# is worth and what is still open. `createdDate` and `updatedDate` come along
# upstream and are dropped, because the voucher date is the one that matters
# for a document and the other two only say when somebody typed it in.
VOUCHER_ROW_DROP = ("createdDate", "updatedDate")

# Repeated on every voucher and answered once by `get_profile`.
VOUCHER_DROP = ("organizationId",)


def voucher_row(item: dict[str, Any]) -> dict[str, Any]:
    """One line of a voucher search result.

    ``archived`` is kept only when true, as in a contact row: it is false on
    nearly every voucher and repeating it costs more than it says.
    """
    row = {key: value for key, value in item.items() if key not in VOUCHER_ROW_DROP}
    if not row.get("archived"):
        row.pop("archived", None)
    return dict(compact(row))


def vouchers_page(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a page of ``GET /v1/voucherlist``."""
    return page(payload, voucher_row, key="vouchers")


def voucher(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one bookkeeping voucher.

    A drop-list rather than an allow-list, so a field added upstream still
    surfaces. Amounts pass through exactly as the API reported them.
    """
    kept = {k: v for k, v in payload.items() if k not in VOUCHER_DROP}
    return dict(compact(kept))


def payments(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize ``GET /v1/payments/{voucherId}``.

    Nothing is dropped by name here. The response is six fields wide and every
    one of them answers part of "has this been paid", including an
    ``openAmount`` of ``0``, which :func:`compact` keeps on purpose.
    """
    return dict(compact(payload))


# Identical on every document and answered once by `get_profile`, exactly as
# on a bookkeeping voucher.
SALES_DOCUMENT_DROP = ("organizationId",)


def sales_document(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one sales document.

    A drop-list rather than an allow-list: the seven types differ from each
    other field by field, and an allow-list would silently swallow whatever
    makes a dunning a dunning. Amounts and their currency pass through
    exactly as the API reported them.

    What survives is what the API sent. A `draft` carries no `files` block
    and no `dueDate`, which is how the answer says there is nothing to
    download yet.
    """
    kept = {k: v for k, v in payload.items() if k not in SALES_DOCUMENT_DROP}
    return dict(compact(kept))


def _row_text(row: dict[str, Any]) -> str:
    """Every text a row carries, lowercased, except its id.

    An id is a UUID: matching a search term against it would only ever fire by
    accident, and a caller who has the id does not need to search for it.
    """
    return " ".join(
        value.lower()
        for key, value in row.items()
        if key != "id" and isinstance(value, str)
    )


def master_data(
    kind: str,
    entries: list[Any],
    *,
    search: str | None = None,
    limit: int,
) -> dict[str, Any]:
    """Trim one master data list to something an answer can carry.

    These lists are long - 257 countries and 231 posting categories in a live
    account - and they arrive whole, because the endpoints do not page. The
    trimming therefore happens here rather than upstream, and the answer says
    how much it left out: ``total`` is what the account holds, ``matched``
    what the search found, and ``shown`` what is in the answer. When ``shown``
    is smaller than the other two, a narrower search is the way on.

    Nothing is dropped from a row. Every field of these four kinds carries a
    decision - whether a category needs a contact, whether a layout is the
    default one - so there is nothing here to leave out.
    """
    rows = [dict(compact(entry)) for entry in entries if isinstance(entry, dict)]
    if search:
        needle = search.lower()
        matched = [row for row in rows if needle in _row_text(row)]
    else:
        matched = rows
    result: dict[str, Any] = {"kind": kind, "total": len(rows)}
    if search:
        result["matched"] = len(matched)
    result["shown"] = min(len(matched), limit)
    result["entries"] = matched[:limit]
    return result


# -- articles -------------------------------------------------------------

# Identical on every record, and answered once by `get_profile`.
ARTICLE_DROP = ("organizationId",)

# A row is for choosing between articles, and these three are for reading one
# that has been chosen. `description` and `note` are free text with no length
# limit worth relying on, and the timestamps say when somebody typed it in.
ARTICLE_ROW_DROP = (
    *ARTICLE_DROP,
    "description",
    "note",
    "createdDate",
    "updatedDate",
)


def article_row(item: dict[str, Any]) -> dict[str, Any]:
    """One line of an article search result.

    A drop-list rather than an allow-list, as everywhere else, so a field
    added upstream still surfaces. ``archived`` is kept only when true, as in
    a contact or voucher row.
    """
    row = {key: value for key, value in item.items() if key not in ARTICLE_ROW_DROP}
    if not row.get("archived"):
        row.pop("archived", None)
    return dict(compact(row))


def articles_page(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a page of ``GET /v1/articles``."""
    return page(payload, article_row, key="articles")


def article(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one article.

    The price block passes through whole. It carries both a net and a gross
    figure with the tax rate between them, and which of the two is the one
    somebody typed is `leadingPrice` - dropping either half would leave a
    number that cannot be checked against anything.
    """
    kept = {k: v for k, v in payload.items() if k not in ARTICLE_DROP}
    return dict(compact(kept))


# -- recurring templates --------------------------------------------------

# Identical on every record, and answered once by `get_profile`. Nothing else
# is dropped: the API already sends a shorter row in a list than it sends for
# one record, so trimming further would take away a field it chose to include.
RECURRING_DROP = ("organizationId",)


def recurring_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one recurring template.

    Verified 2026-08-21 against a live one. The same function serves a list
    row and a full record, which differ by twelve fields upstream - see
    SPECS.md section 5.
    """
    kept = {k: v for k, v in payload.items() if k not in RECURRING_DROP}
    return dict(compact(kept))


def recurring_templates_page(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a page of ``GET /v1/recurring-templates``."""
    return page(payload, recurring_template, key="templates")
