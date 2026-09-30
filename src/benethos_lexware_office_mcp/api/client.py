"""All HTTP access to the Lexware Office API.

Nothing else in this package talks to the network. The client owns the single
shared token bucket, decides what may be retried, and maps every upstream
status onto a :class:`~.errors.ToolError`.

The retry rules are the part worth reading twice (SPECS.md section 10.2). A
duplicate request here can create a second invoice with a consecutive number
in someone's bookkeeping, which the caller cannot undo. So retrying is decided
per method **and** per failure mode:

===========================  ======  ============  ======
Failure                      GET     PUT, DELETE   POST
===========================  ======  ============  ======
429                          retry   retry         retry
5xx                          retry   retry         never
timeout, connection reset    retry   retry         never
4xx other than 429           never   never         never
===========================  ======  ============  ======

429 is the exception because the documentation states that "the actual call
will not be performed" — the one failure mode whose outcome is certain.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx

from .. import __version__, logbook
from ..config import DEFAULT_PAGE_SIZE, Settings
from ..errors import RateLimitError, UpstreamError, ValidationError
from .ratelimit import Sleeper, TokenBucket
from .refusal import from_response

__all__ = ["ClientProvider", "LexwareClient"]

# PUT and DELETE are idempotent, and an update additionally carries the
# `version` it read: if the first attempt succeeded the version has moved on
# and a retry fails with 409 rather than applying the change twice.
RETRYABLE_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE"})

MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.5
BACKOFF_CAP = 8.0

# Consecutive 429s across requests before the bucket is held shut. Backing off
# harder is what turns a transient limit into a permanently blocked key.
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN = 30.0


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


class LexwareClient:
    """Async HTTP client for the API.

    One instance per server process, holding one connection pool and one
    token bucket.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        bucket: TokenBucket | None = None,
        sleep: Sleeper | None = None,
    ) -> None:
        self.settings = settings
        self._bucket = bucket or TokenBucket(settings.rate, settings.burst)
        self._sleep = sleep or asyncio.sleep
        self._consecutive_429 = 0
        self._http = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.timeout,
            transport=transport,
            headers={
                "Accept": "application/json",
                "User-Agent": f"benethos-lexware-office-mcp/{__version__}",
            },
        )

    async def __aenter__(self) -> LexwareClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- requests ---------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        files: Any = None,
        data: Any = None,
        accept: str | None = None,
    ) -> httpx.Response:
        """Perform one API call, with rate limiting, retries and error mapping.

        ``accept`` overrides the client's default of ``application/json``,
        which matters for anything that comes back as bytes: asking a download
        endpoint for JSON is asking the wrong question.
        """
        method = method.upper()
        retryable = method in RETRYABLE_METHODS
        headers = {"Authorization": f"Bearer {self.settings.require_api_key()}"}
        if accept is not None:
            headers["Accept"] = accept
        last_attempt = MAX_ATTEMPTS - 1
        # Whether an earlier attempt may have been carried out: it timed out,
        # lost its connection or got a 5xx. A 429 is certain not to have been.
        maybe_done = False

        for attempt in range(MAX_ATTEMPTS):
            number = attempt + 1
            queued_at = time.perf_counter()
            await self._bucket.acquire()
            logbook.tally.api_call()
            sent_at = time.perf_counter()
            queued = (sent_at - queued_at) * 1000
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    files=files,
                    data=data,
                    headers=headers,
                )
            except httpx.TimeoutException as exc:
                logbook.api.unanswered(method, path, exc, _since(sent_at), number)
                # Not a 429, so the streak the breaker counts is over. Left
                # standing, two 429s either side of a timeout would trip it.
                self._consecutive_429 = 0
                if retryable and attempt < last_attempt:
                    maybe_done = True
                    await self._retry(method, path, attempt, error=exc)
                    continue
                raise UpstreamError(
                    f"{method} {path} timed out.", outcome_unknown=not retryable
                ) from exc
            except httpx.TransportError as exc:
                logbook.api.unanswered(method, path, exc, _since(sent_at), number)
                self._consecutive_429 = 0
                if retryable and attempt < last_attempt:
                    maybe_done = True
                    await self._retry(method, path, attempt, error=exc)
                    continue
                raise UpstreamError(
                    f"{method} {path} could not be completed: {exc}.",
                    outcome_unknown=not retryable,
                ) from exc

            status = response.status_code
            logbook.api.answered(method, path, status, _since(sent_at), number, queued)

            if status == 429:
                # Safe to repeat for any method: the call was not performed.
                self._consecutive_429 += 1
                if self._consecutive_429 >= BREAKER_THRESHOLD:
                    self._bucket.drain(BREAKER_COOLDOWN)
                    logbook.api.breaker_tripped(self._consecutive_429, BREAKER_COOLDOWN)
                    self._consecutive_429 = 0
                    raise RateLimitError(
                        "Rate limited repeatedly. Pausing for "
                        f"{BREAKER_COOLDOWN:.0f} seconds. The Lexware limit of "
                        "2 requests per second covers your whole account, so "
                        "another client may be spending it too."
                    )
                if attempt < last_attempt:
                    await self._retry(
                        method,
                        path,
                        attempt,
                        status=status,
                        retry_after=response.headers.get("Retry-After"),
                    )
                    continue
                limited = RateLimitError(
                    "Rate limited. Retrying did not clear it, try again shortly."
                )
                limited.status = status
                raise limited

            self._consecutive_429 = 0

            if status >= 500:
                if retryable and attempt < last_attempt:
                    maybe_done = True
                    await self._retry(method, path, attempt, status=status)
                    continue
                failed = UpstreamError(
                    f"The API returned {status} for {method} {path}.",
                    outcome_unknown=not retryable,
                )
                failed.status = status
                raise failed

            if status == 404 and method == "DELETE" and maybe_done:
                # The retry of a delete finding nothing is the delete having
                # worked: the attempt whose answer was lost removed it.
                # Reporting 404 would tell the caller the record never
                # existed, right after this call destroyed it.
                return response

            if status == 401:
                logbook.api.key_rejected()
            if status >= 400:
                raise from_response(response, method, path)

            return response

        raise UpstreamError(f"{method} {path} failed after {MAX_ATTEMPTS} attempts.")

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """GET a path and decode its JSON body."""
        response = await self.request("GET", path, params=params)
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(f"GET {path} returned a malformed body.") from exc

    async def _send_json(
        self, method: str, path: str, *, endpoint: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Send a write and decode the object it answers with.

        The request was accepted by the time a body is read, so a body that
        is not a JSON object - empty, HTML from a proxy, a truncated stream -
        is not a failed write. It is a write whose result nobody saw, and it
        is reported as one: a plain ``ValueError`` here would reach the model
        as "Error executing tool" and invite the very retry that makes a
        second record.
        """
        response = await self.request(method, path, **kwargs)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise UpstreamError(
                f"{method} {path} was accepted with {response.status_code}, but "
                f"the {endpoint} endpoint's answer could not be read.",
                outcome_unknown=True,
            )
        return payload

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

    async def download(self, path: str, accept: str | None = None) -> httpx.Response:
        """GET something that comes back as bytes rather than JSON.

        The response is returned whole, because a caller needs the body, the
        content type and the filename the server suggested, and only the
        response carries all three.
        """
        return await self.request("GET", path, accept=accept)

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

    # -- internals --------------------------------------------------------

    async def _retry(
        self,
        method: str,
        path: str,
        attempt: int,
        *,
        status: int = 0,
        error: BaseException | None = None,
        retry_after: str | None = None,
    ) -> None:
        """Say why the next attempt follows, then wait for it."""
        wait = _backoff(attempt, retry_after)
        if error is not None:
            logbook.api.retrying_error(method, path, error, wait, attempt + 2)
        else:
            logbook.api.retrying_status(method, path, status, wait, attempt + 2)
        await self._sleep(wait)


def _since(started: float) -> float:
    """Milliseconds since ``started``, a ``perf_counter`` reading."""
    return (time.perf_counter() - started) * 1000


def _backoff(attempt: int, retry_after: str | None = None) -> float:
    """How long to wait before the next attempt, Retry-After honoured."""
    delay = min(BACKOFF_BASE * (2**attempt), BACKOFF_CAP)
    if retry_after:
        try:
            asked = float(retry_after)
        except ValueError:
            # A Retry-After can also be an HTTP date. Falling back to the
            # computed delay is better than failing to back off at all.
            logbook.api.retry_after_unreadable()
        else:
            # Honoured up to the cap and no further. This wait happens
            # inside a tool call, so `86400` would hold it for a day and
            # `inf` for ever - better to say so and let the caller decide.
            if not math.isfinite(asked) or asked > BACKOFF_CAP:
                logbook.api.retry_after_too_long(asked)
                raise RateLimitError(
                    f"Rate limited, and the API asked to wait {retry_after} "
                    "seconds, longer than this call waits. Try again later."
                )
            logbook.api.retry_after_honoured(asked)
            delay = max(delay, asked)
    # Jitter, so that several waiters do not resume in lockstep.
    return delay * (0.5 + random.random() / 2)


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
