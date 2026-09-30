"""The Lexware Office API, one method per endpoint.

Every method is one API call through the mechanics in ``connection``: the
limiter, the retry rules and the error mapping apply without a method having
to ask. What each endpoint takes and answers was measured where the
docstring says so.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from ..errors import UpstreamError, ValidationError
from ..settings import DEFAULT_PAGE_SIZE, Settings
from .connection import Connection

__all__ = ["ClientProvider", "LexwareClient"]


def _segment(value: str) -> str:
    """One id as one path segment, whatever it contains.

    Ids come from the model. Put into a path as they stand, a slash, ``?`` or
    ``#`` in one would reach another endpoint - ``x/../../articles/y`` turns
    an update of a contact into one of an article. Percent-encoding keeps a
    slash inside the segment, and ``.``, ``..`` and an empty id, which
    encoding leaves as they are and a URL then resolves, are refused.
    """
    if value.strip() in ("", ".", ".."):
        raise ValidationError(f"{value!r} is not an id. Take one from a search.")
    return quote(value, safe="")


def _page_params(page: int, size: int, **filters: Any) -> dict[str, Any]:
    """Query parameters for a list endpoint.

    A filter left unset must be absent from the query string, not sent as the
    string "None", which is what happens if the dictionary is handed to httpx
    with its nulls still in it.
    """
    params: dict[str, Any] = {"page": page, "size": size}
    params.update({key: value for key, value in filters.items() if value is not None})
    return params


def _expect_object(payload: Any, endpoint: str) -> dict[str, Any]:
    """Insist that an endpoint documented to return an object returned one."""
    if not isinstance(payload, dict):
        raise UpstreamError(f"The {endpoint} endpoint returned an unexpected shape.")
    return payload


def _expect_list(payload: Any, endpoint: str) -> list[Any]:
    """Insist that an endpoint documented to return a bare list returned one."""
    if not isinstance(payload, list):
        raise UpstreamError(f"The {endpoint} endpoint returned an unexpected shape.")
    return payload


class LexwareClient(Connection):
    """Async client for the API: the endpoints, over one :class:`Connection`.

    One instance per server process, handed out by :class:`ClientProvider`.
    """

    # -- endpoints --------------------------------------------------------

    async def profile(self) -> dict[str, Any]:
        """``GET /v1/profile``. One API call."""
        return _expect_object(await self.get_json("/v1/profile"), "profile")

    async def contacts(
        self,
        *,
        name: str | None = None,
        email: str | None = None,
        number: int | None = None,
        customer: bool | None = None,
        vendor: bool | None = None,
        page: int = 0,
        size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """``GET /v1/contacts``. One API call returning **one** page.

        Paging is the caller's business on purpose. Walking every page here
        would turn one tool call into an unbounded number of API calls against
        a limit that covers the whole account.

        Filters combine with AND upstream. ``name`` and ``email`` are
        case-insensitive substring matches and are rejected below three
        characters (verified 2026-08-20).
        """
        params = _page_params(
            page,
            size,
            name=name,
            email=email,
            number=number,
            customer=customer,
            vendor=vendor,
        )
        return _expect_object(
            await self.get_json("/v1/contacts", params=params), "contacts"
        )

    async def contact(self, contact_id: str) -> dict[str, Any]:
        """``GET /v1/contacts/{id}``. One API call."""
        return _expect_object(
            await self.get_json(f"/v1/contacts/{_segment(contact_id)}"), "contacts"
        )

    async def create_contact(self, body: dict[str, Any]) -> dict[str, Any]:
        """``POST /v1/contacts``. One API call, never retried.

        Returns the small envelope the API answers a creation with:
        ``{id, resourceUri, createdDate, updatedDate, version}``. The record
        itself has to be read back if the caller wants to see it.
        """
        return await self._send_json(
            "POST", "/v1/contacts", json=body, endpoint="contacts"
        )

    async def update_contact(
        self, contact_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """``PUT /v1/contacts/{id}``. One API call.

        The body replaces the record, so it has to be complete. It also has to
        carry the ``version`` that was read, which is what makes a concurrent
        change fail instead of being overwritten.
        """
        return await self._send_json(
            "PUT",
            f"/v1/contacts/{_segment(contact_id)}",
            json=body,
            endpoint="contacts",
        )

    # -- vouchers ---------------------------------------------------------

    async def voucherlist(
        self,
        *,
        voucher_type: str,
        voucher_status: str,
        contact_id: str | None = None,
        voucher_number: str | None = None,
        voucher_date_from: str | None = None,
        voucher_date_to: str | None = None,
        only_overdue: bool | None = None,
        only_open: bool | None = None,
        archived: bool | None = None,
        sort: str | None = None,
        page: int = 0,
        size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """``GET /v1/voucherlist``. One API call returning **one** page.

        The index over every sales and bookkeeping document, and the only way
        to find one without already knowing its id. ``voucherType`` and
        ``voucherStatus`` are **required** by the API, not optional filters
        (verified 2026-08-20), so the caller always states both even if only
        to say ``any``. ``voucherNumber`` matches the whole number, ignoring
        case, and never a part of it (measured 2026-09-27).
        """
        params = _page_params(
            page,
            size,
            voucherType=voucher_type,
            voucherStatus=voucher_status,
            contactId=contact_id,
            voucherNumber=voucher_number,
            voucherDateFrom=voucher_date_from,
            voucherDateTo=voucher_date_to,
            onlyOverdue=only_overdue,
            onlyOpen=only_open,
            archived=archived,
            sort=sort,
        )
        return _expect_object(
            await self.get_json("/v1/voucherlist", params=params), "voucherlist"
        )

    async def voucher(self, voucher_id: str) -> dict[str, Any]:
        """``GET /v1/vouchers/{id}``. One API call."""
        return _expect_object(
            await self.get_json(f"/v1/vouchers/{_segment(voucher_id)}"), "vouchers"
        )

    async def vouchers_by_number(self, voucher_number: str) -> dict[str, Any]:
        """``GET /v1/vouchers?voucherNumber=``. One API call.

        A page of whole vouchers rather than of rows, so a lookup by number
        costs one call where ``voucherlist`` would need a second to read the
        record. The documentation marks this filter deprecated in favour of
        ``voucherlist``'s own, which finds sales documents as well. It still
        answers, measured 2026-09-27, and ``live/smoke.py`` is what will see
        the day it stops.
        """
        return _expect_object(
            await self.get_json(
                "/v1/vouchers", params={"voucherNumber": voucher_number}
            ),
            "vouchers",
        )

    async def payments(self, voucher_id: str) -> dict[str, Any]:
        """``GET /v1/payments/{voucherId}``. One API call.

        Takes the id of the **voucher**, not of a payment.
        """
        return _expect_object(
            await self.get_json(f"/v1/payments/{_segment(voucher_id)}"), "payments"
        )

    async def create_voucher(self, body: dict[str, Any]) -> dict[str, Any]:
        """``POST /v1/vouchers``. One API call, never retried."""
        return await self._send_json(
            "POST", "/v1/vouchers", json=body, endpoint="vouchers"
        )

    async def update_voucher(
        self, voucher_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """``PUT /v1/vouchers/{id}``. One API call.

        As with contacts the body replaces the record and has to carry the
        ``version`` that was read.
        """
        return await self._send_json(
            "PUT",
            f"/v1/vouchers/{_segment(voucher_id)}",
            json=body,
            endpoint="vouchers",
        )

    # -- articles ---------------------------------------------------------

    async def articles(
        self,
        *,
        article_number: str | None = None,
        gtin: str | None = None,
        article_type: str | None = None,
        page: int = 0,
        size: int = DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """``GET /v1/articles``. One API call, one page.

        Only these three filter. Measured 2026-08-21: an unknown parameter is
        ignored rather than refused, so a `query` or `title` that looks like a
        text search silently returns the whole list.
        """
        params = _page_params(
            page,
            size,
            articleNumber=article_number,
            gtin=gtin,
            type=article_type,
        )
        return _expect_object(
            await self.get_json("/v1/articles", params=params), "articles"
        )

    async def article(self, article_id: str) -> dict[str, Any]:
        """``GET /v1/articles/{id}``. One API call."""
        return _expect_object(
            await self.get_json(f"/v1/articles/{_segment(article_id)}"), "articles"
        )

    async def create_article(self, body: dict[str, Any]) -> dict[str, Any]:
        """``POST /v1/articles``. One API call, never retried."""
        return await self._send_json(
            "POST", "/v1/articles", json=body, endpoint="articles"
        )

    async def update_article(
        self, article_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """``PUT /v1/articles/{id}``. One API call.

        The body replaces the record and has to carry the ``version`` that was
        read. Verified 2026-08-21: a stale one is refused with **409**, where
        a contact answers 406.
        """
        return await self._send_json(
            "PUT",
            f"/v1/articles/{_segment(article_id)}",
            json=body,
            endpoint="articles",
        )

    async def delete_article(self, article_id: str) -> None:
        """``DELETE /v1/articles/{id}``. One API call, and it cannot be undone.

        Verified 2026-08-21: the answer is **204** with an empty body, the
        record is gone rather than archived, and a second delete of the same
        id is a 404.
        """
        await self.request("DELETE", f"/v1/articles/{_segment(article_id)}")

    # -- recurring templates ----------------------------------------------

    async def recurring_templates(
        self,
        *,
        page: int = 0,
        size: int = DEFAULT_PAGE_SIZE,
        sort: str | None = None,
    ) -> dict[str, Any]:
        """``GET /v1/recurring-templates``. One API call, one page.

        There is nothing to filter by. Measured 2026-08-21: the endpoint takes
        paging and a ``sort``, which is checked against four date fields and
        refuses anything else, and it ignores every other parameter.
        """
        params = _page_params(page, size, sort=sort)
        return _expect_object(
            await self.get_json("/v1/recurring-templates", params=params),
            "recurring-templates",
        )

    async def recurring_template(self, template_id: str) -> dict[str, Any]:
        """``GET /v1/recurring-templates/{id}``. One API call."""
        return _expect_object(
            await self.get_json(f"/v1/recurring-templates/{_segment(template_id)}"),
            "recurring-templates",
        )

    # -- master data ------------------------------------------------------

    async def master_data(self, kind: str) -> list[Any]:
        """``GET /v1/{kind}``. One API call.

        The four master data endpoints answer with a **bare JSON list** rather
        than with the page envelope every other list endpoint uses, so there
        is nothing to page and no page parameters to pass. Measured on
        2026-08-21 for all four.
        """
        return _expect_list(await self.get_json(f"/v1/{kind}"), kind)

    # -- sales documents --------------------------------------------------

    async def create_sales_document(
        self,
        resource: str,
        body: dict[str, Any],
        *,
        finalize: bool = False,
        preceding_sales_voucher_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/{resource}``. One API call, never retried.

        Both modifiers are query parameters, measured 2026-08-21.
        ``finalize=true`` creates the document as `open` rather than as a
        draft, which the API cannot undo. ``precedingSalesVoucherId`` follows
        an existing document, and a dunning is refused without it before its
        body is even looked at.
        """
        params: dict[str, Any] = {}
        if finalize:
            params["finalize"] = "true"
        if preceding_sales_voucher_id is not None:
            params["precedingSalesVoucherId"] = preceding_sales_voucher_id
        return await self._send_json(
            "POST",
            f"/v1/{resource}",
            json=body,
            params=params or None,
            endpoint=resource,
        )

    async def sales_document(self, resource: str, document_id: str) -> dict[str, Any]:
        """``GET /v1/{resource}/{id}``. One API call.

        The document itself, whatever state it is in. Verified 2026-08-21
        against a live invoice in both `draft` and `open`. A `resource` that
        does not match the id is a 404, indistinguishable from an id that
        does not exist.
        """
        return _expect_object(
            await self.get_json(f"/v1/{resource}/{_segment(document_id)}"), resource
        )

    # -- files ------------------------------------------------------------

    async def file(self, file_id: str, accept: str | None = None) -> httpx.Response:
        """``GET /v1/files/{id}``. One API call.

        Verified 2026-08-20: the body is the file, the content type is the
        file's own, and ``Content-Disposition`` names it ``{id}.{extension}``.
        Asking for ``application/xml`` when the file is a PDF is a 404 rather
        than a 406.
        """
        return await self.download(f"/v1/files/{_segment(file_id)}", accept)

    async def document_file(
        self, resource: str, document_id: str, accept: str | None = None
    ) -> httpx.Response:
        """``GET /v1/{resource}/{id}/file``. One API call.

        The rendered document itself. Verified 2026-08-21: the body is the
        PDF and ``Content-Disposition`` carries the document's own name. A
        bookkeeping voucher answers this path with 404, and a draft with 409.
        """
        return await self.download(
            f"/v1/{resource}/{_segment(document_id)}/file", accept
        )

    async def upload_file(
        self, content: bytes, filename: str, content_type: str
    ) -> dict[str, Any]:
        """``POST /v1/files``. One API call, never retried.

        Verified 2026-08-20: the form part must be named ``file``, the
        ``type`` field is required and ``voucher`` is its only accepted value,
        and the answer is **202** with ``{id, voucherId}``. Uploading does not
        only store a file, it also creates the bookkeeping voucher the file
        belongs to, which is why this is a write in every sense.
        """
        return await self._send_json(
            "POST",
            "/v1/files",
            files={"file": (filename, content, content_type)},
            data={"type": "voucher"},
            endpoint="files",
        )

    async def attach_file(
        self, voucher_id: str, content: bytes, filename: str, content_type: str
    ) -> dict[str, Any]:
        """``POST /v1/vouchers/{id}/files``. One API call, never retried.

        Verified 2026-08-21: the part is named ``file`` and **no ``type``
        field is wanted** here, unlike ``/v1/files``. The answer is **202**
        with ``{id}`` alone, and the voucher carries that id in its ``files``
        list afterwards. The route is plural and POST only — the
        documentation writes it singular and gives it a GET, and neither
        exists.
        """
        return await self._send_json(
            "POST",
            f"/v1/vouchers/{_segment(voucher_id)}/files",
            files={"file": (filename, content, content_type)},
            endpoint="voucher files",
        )


class ClientProvider:
    """Hands out the one client a server process is allowed to have.

    Tools must not build their own client. Each ``LexwareClient`` carries its
    own token bucket and connection pool, so a client per tool call would mean
    a rate limiter per tool call — every one of them starting full, every one
    of them convinced it was within the limit, and together far past the two
    requests per second the account actually has.

    Creation is lazy, so building a server to list its tools does not open a
    connection pool that nobody uses.
    """

    def __init__(self, settings: Settings, **kwargs: Any) -> None:
        self._settings = settings
        self._kwargs = kwargs
        self._client: LexwareClient | None = None

    def get(self) -> LexwareClient:
        """The process-wide client, built on first use."""
        if self._client is None:
            self._client = LexwareClient(self._settings, **self._kwargs)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
