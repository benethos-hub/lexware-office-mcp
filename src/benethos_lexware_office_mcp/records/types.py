"""What a caller can say, and the shape of what the file tools answer.

Every enumeration a tool takes and every model its arguments are built from,
in one place: the schema a client sees is generated from these, so this
module is the vocabulary of the whole tool list. The values were measured
against the API where a comment says so, and a value the API does not take
does not belong here. The two answer models are here for the same reason:
the output schema is generated from them.

Nothing here builds a request or reads a response. Building a request
body from these is ``payloads``, reading an answer back is ``formatting``.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field

__all__ = [
    "RESOURCES",
    "Address",
    "ArticleType",
    "ContactKind",
    "CreatableType",
    "Delivered",
    "DocumentType",
    "Download",
    "Format",
    "LeadingPrice",
    "LinkAction",
    "LineItemType",
    "LinkTarget",
    "MasterDataKind",
    "RecurringSort",
    "Role",
    "RoleFilter",
    "SalesLineItem",
    "SearchStatus",
    "SearchType",
    "SortOrder",
    "TaxType",
    "VoucherItem",
    "VoucherType",
]

# -- contacts -------------------------------------------------------------

ContactKind = Literal["company", "person"]
Role = Literal["customer", "vendor"]

RoleFilter = Literal["customer", "vendor", "any"]


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


# -- vouchers -------------------------------------------------------------

# Measured against the live API on 2026-08-20 by trying every plausible value:
# these are exactly the ones it accepts. `dunning` is not among them, so
# dunnings cannot be found through the voucher list at all.
SearchType = Literal[
    "any",
    "invoice",
    "salesinvoice",
    "purchaseinvoice",
    "creditnote",
    "salescreditnote",
    "purchasecreditnote",
    "orderconfirmation",
    "quotation",
    "deliverynote",
    "downpaymentinvoice",
]

SearchStatus = Literal[
    "any",
    "draft",
    "open",
    "paid",
    "paidoff",
    "voided",
    "transferred",
    "sepadebit",
    "overdue",
    "accepted",
    "rejected",
    "unchecked",
]

# The four properties the API sorts the voucher list on, each way round.
# Measured 2026-09-27: all four are honoured, and anything else is refused
# with "parameter 'sort' is invalid".
SortOrder = Literal[
    "voucherDate,DESC",
    "voucherDate,ASC",
    "voucherNumber,DESC",
    "voucherNumber,ASC",
    "createdDate,DESC",
    "createdDate,ASC",
    "updatedDate,DESC",
    "updatedDate,ASC",
]

VoucherType = Literal[
    "salesinvoice", "salescreditnote", "purchaseinvoice", "purchasecreditnote"
]
# One vocabulary for a voucher and for a sales document: both say whether
# the line amounts are before or after tax, in the same three words.
TaxType = Literal["net", "gross", "vatfree"]


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


# -- articles -------------------------------------------------------------

ArticleType = Literal["PRODUCT", "SERVICE"]
LeadingPrice = Literal["NET", "GROSS"]


# -- sales documents ------------------------------------------------------

# The six types the API creates. A down payment invoice has no POST at all -
# it is raised by the app when a quotation is part-invoiced. Measured against
# the documented endpoint list and confirmed by the six that do accept one,
# 2026-08-21.
CreatableType = Literal[
    "invoice",
    "quotation",
    "credit-note",
    "order-confirmation",
    "delivery-note",
    "dunning",
]

# The seven types there are. A nested Literal is flattened, so the schema
# lists all seven and a new type is added in exactly one place.
DocumentType = Literal[CreatableType, "down-payment-invoice"]

# The path segment each type lives under: plural and kebab-cased, which is
# also what the web app's permalinks use. Every one of the seven pluralizes
# with an `s`, so the table is derived rather than kept by hand.
RESOURCES: dict[str, str] = {name: f"{name}s" for name in get_args(DocumentType)}

# Measured 2026-08-21 by sending `title`: the API names the four it takes.
RecurringSort = Literal[
    "createdDate,DESC",
    "createdDate,ASC",
    "updatedDate,DESC",
    "updatedDate,ASC",
    "nextExecutionDate,DESC",
    "nextExecutionDate,ASC",
    "lastExecutionDate,DESC",
    "lastExecutionDate,ASC",
]

LineItemType = Literal["custom", "material", "service", "text"]


class SalesLineItem(BaseModel):
    """One line of a sales document.

    The price is one number, and which side it is comes from the document's
    tax type rather than from the line: a `net` document carries net line
    prices throughout. The API adds the totals up itself, so nothing here is
    summed.
    """

    name: str = Field(description="What the line is called on the document.")
    quantity: float = Field(description="How many units.", ge=0)
    unit_name: str = Field(description="What one unit is, for example 'Stueck'.")
    unit_price: float = Field(
        description=(
            "The price of one unit, before tax on a 'net' document and after "
            "tax on a 'gross' one."
        ),
        ge=0,
    )
    tax_rate_percent: float = Field(
        description="The tax rate for this line, for example 19.", ge=0
    )
    description: str | None = Field(
        None, description="Longer text under the line's name."
    )
    discount_percentage: float | None = Field(
        None, description="Discount on this line, as a percentage.", ge=0, le=100
    )
    item_type: LineItemType = Field(
        "custom",
        description=(
            "'custom' is a line typed out here. 'material' or 'service' quote "
            "an article and need article_id. 'text' is a note with no price."
        ),
    )
    article_id: str | None = Field(
        None,
        description=(
            "The article this line quotes, from search_articles. Only for "
            "'material' and 'service'."
        ),
    )


# -- links ----------------------------------------------------------------

# Deeplinks reach further than documents do, but not to a stored file:
# the web app has no page for one. Verified 2026-08-21, see SPECS.md
# section 5.
LinkTarget = Literal[DocumentType, "contact", "voucher"]

# What a permalink can do with a record, requested against the live app on
# 2026-08-21. A contact has one page and answers only to `view`.
LinkAction = Literal["view", "edit"]


# -- master data ----------------------------------------------------------

# The path segment is the kind, for all four. The value reaches a URL only
# after the schema has checked it against this list, so nothing here is
# assembled from an unchecked string.
MasterDataKind = Literal[
    "countries",
    "payment-conditions",
    "posting-categories",
    "print-layouts",
]


# -- files ----------------------------------------------------------------

Format = Literal["pdf", "xml"]


class Download(BaseModel):
    """What a download reports back.

    Declared as a model rather than a bare dict so the schema the client sees
    says what the fields are. `path` and `uri` name the same file: the path is
    usable when the client shares a machine with the server, the URI when it
    does not.
    """

    path: str = Field(description="Where the file was written on the server.")
    uri: str = Field(
        description=(
            "Resource URI for the same file. Read it to get the bytes, "
            "wherever the server runs."
        )
    )
    mimeType: str = Field(description="The file's content type.")
    size: int = Field(description="Size in bytes.")
    # No deeplink. A download reports where the bytes are, and a link into
    # the web app is `get_deeplink`'s answer to a different question. Keeping
    # them apart is what stops one from being wrong about the other, see
    # SPECS.md section 13.


class Delivered(BaseModel):
    """What `read_download` reports alongside the content it delivers."""

    uri: str = Field(description="The download that was read.")
    mimeType: str = Field(description="The file's content type.")
    size: int = Field(description="Size in bytes.")
    deliveredAs: str = Field(
        description=(
            "How the content was put into the answer: 'text' for something "
            "readable such as an XRechnung, 'image' for a picture, 'pages' "
            "for a PDF rendered to images, or 'binary' for anything the "
            "client has to handle itself."
        )
    )
    pages: int | None = Field(
        None, description="How many pages the document has, for a PDF."
    )
    pagesShown: int | None = Field(
        None, description="How many of them were rendered into this answer."
    )
