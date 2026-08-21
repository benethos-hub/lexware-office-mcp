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
import logging
import random
from types import TracebackType
from typing import Any

import httpx

from . import __version__
from .config import DEFAULT_PAGE_SIZE, Settings
from .errors import (
    AuthError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    UpstreamError,
    ValidationError,
)
from .ratelimit import TokenBucket

logger = logging.getLogger(__name__)

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


def _json_object(response: httpx.Response) -> dict[str, Any]:
    """The response body as a useful mapping, or an empty one.

    A bare JSON string is a body too: the files endpoint answers an unknown
    upload type with ``"Invalid or missing upload type."`` and nothing else.
    Wrapping it keeps that sentence instead of discarding it for not being an
    object.
    """
    try:
        body = response.json()
    except ValueError:
        return {}
    if isinstance(body, str):
        return {"message": body}
    return body if isinstance(body, dict) else {}


def _detail_text(body: dict[str, Any]) -> str:
    """The API's own wording for a failure, without ever echoing the key.

    Three shapes are in use upstream and all three carry the only information
    there is: ``errorCode``/``message``, an ``IssueList``, and a single issue
    flattened onto the top level, which is how the files endpoint reports a
    missing form field.
    """
    parts = [str(body[key]) for key in ("errorCode", "message") if body.get(key)]
    parts.extend(_issue_texts(body.get("IssueList")))
    if "IssueList" not in body:
        parts.extend(_issue_texts([body]))
    text = " ".join(dict.fromkeys(part for part in parts if part)).strip()
    return f" {text}" if text else ""


def _issue_sources(body: dict[str, Any]) -> set[str]:
    """Which fields an error blamed.

    The status alone does not say what went wrong: contacts answer a missing
    role, a second billing address and a stale version all with 406. The
    ``source`` is what tells those apart.
    """
    issues = body.get("IssueList")
    if not isinstance(issues, list):
        issues = [body] if body.get("source") else []
    return {
        str(issue["source"])
        for issue in issues
        if isinstance(issue, dict) and issue.get("source")
    }


def _issue_texts(issues: Any) -> list[str]:
    """Flatten the API's ``IssueList`` into readable fragments.

    A rejected query parameter comes back as
    ``{"source": "number", "i18nKey": "invalid_value"}`` and nothing else, so
    dropping either half leaves the caller guessing which field was wrong or
    what was wrong with it.
    """
    if not isinstance(issues, list):
        return []
    texts = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        source = str(issue.get("source") or "")
        kind = str(issue.get("i18nKey") or issue.get("type") or "")
        if source and kind:
            texts.append(f"{source}: {kind}")
        elif source or kind:
            texts.append(source or kind)
    return texts


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
        sleep: Any = None,
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

        for attempt in range(MAX_ATTEMPTS):
            await self._bucket.acquire()
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
                if retryable and attempt < last_attempt:
                    await self._backoff(attempt)
                    continue
                raise UpstreamError(
                    f"{method} {path} timed out.", outcome_unknown=not retryable
                ) from exc
            except httpx.TransportError as exc:
                if retryable and attempt < last_attempt:
                    await self._backoff(attempt)
                    continue
                raise UpstreamError(
                    f"{method} {path} could not be completed: {exc}.",
                    outcome_unknown=not retryable,
                ) from exc

            status = response.status_code

            if status == 429:
                # Safe to repeat for any method: the call was not performed.
                self._consecutive_429 += 1
                if self._consecutive_429 >= BREAKER_THRESHOLD:
                    self._bucket.drain(BREAKER_COOLDOWN)
                    self._consecutive_429 = 0
                    raise RateLimitError(
                        "Rate limited repeatedly. Pausing for "
                        f"{BREAKER_COOLDOWN:.0f} seconds. The Lexware limit of "
                        "2 requests per second covers your whole account, so "
                        "another client may be spending it too."
                    )
                if attempt < last_attempt:
                    await self._backoff(attempt, response.headers.get("Retry-After"))
                    continue
                raise RateLimitError(
                    "Rate limited. Retrying did not clear it, try again shortly."
                )

            self._consecutive_429 = 0

            if status >= 500:
                if retryable and attempt < last_attempt:
                    await self._backoff(attempt)
                    continue
                raise UpstreamError(
                    f"The API returned {status} for {method} {path}.",
                    outcome_unknown=not retryable,
                )

            if status >= 400:
                raise self._client_error(response, method, path)

            return response

        raise UpstreamError(f"{method} {path} failed after {MAX_ATTEMPTS} attempts.")

    async def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """GET a path and decode its JSON body."""
        response = await self.request("GET", path, params=params)
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(f"GET {path} returned a malformed body.") from exc

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
            await self.get_json(f"/v1/contacts/{contact_id}"), "contacts"
        )

    async def create_contact(self, body: dict[str, Any]) -> dict[str, Any]:
        """``POST /v1/contacts``. One API call, never retried.

        Returns the small envelope the API answers a creation with:
        ``{id, resourceUri, createdDate, updatedDate, version}``. The record
        itself has to be read back if the caller wants to see it.
        """
        response = await self.request("POST", "/v1/contacts", json=body)
        return _expect_object(response.json(), "contacts")

    async def update_contact(
        self, contact_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """``PUT /v1/contacts/{id}``. One API call.

        The body replaces the record, so it has to be complete. It also has to
        carry the ``version`` that was read, which is what makes a concurrent
        change fail instead of being overwritten.
        """
        response = await self.request("PUT", f"/v1/contacts/{contact_id}", json=body)
        return _expect_object(response.json(), "contacts")

    # -- vouchers ---------------------------------------------------------

    async def voucherlist(
        self,
        *,
        voucher_type: str,
        voucher_status: str,
        contact_id: str | None = None,
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
        to say ``any``.
        """
        params = _page_params(
            page,
            size,
            voucherType=voucher_type,
            voucherStatus=voucher_status,
            contactId=contact_id,
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
            await self.get_json(f"/v1/vouchers/{voucher_id}"), "vouchers"
        )

    async def vouchers_by_number(self, voucher_number: str) -> dict[str, Any]:
        """``GET /v1/vouchers?voucherNumber=``. One API call.

        The only lookup by document number the API offers: ``voucherlist``
        cannot filter by number at all. The response is a page of whole
        vouchers rather than of rows.
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
            await self.get_json(f"/v1/payments/{voucher_id}"), "payments"
        )

    async def create_voucher(self, body: dict[str, Any]) -> dict[str, Any]:
        """``POST /v1/vouchers``. One API call, never retried."""
        response = await self.request("POST", "/v1/vouchers", json=body)
        return _expect_object(response.json(), "vouchers")

    async def update_voucher(
        self, voucher_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """``PUT /v1/vouchers/{id}``. One API call.

        As with contacts the body replaces the record and has to carry the
        ``version`` that was read.
        """
        response = await self.request("PUT", f"/v1/vouchers/{voucher_id}", json=body)
        return _expect_object(response.json(), "vouchers")

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

    async def sales_document(self, resource: str, document_id: str) -> dict[str, Any]:
        """``GET /v1/{resource}/{id}``. One API call.

        The document itself, whatever state it is in. Verified 2026-08-21
        against a live invoice in both `draft` and `open`. A `resource` that
        does not match the id is a 404, indistinguishable from an id that
        does not exist.
        """
        return _expect_object(
            await self.get_json(f"/v1/{resource}/{document_id}"), resource
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
        return await self.download(f"/v1/files/{file_id}", accept)

    async def document_file(
        self, resource: str, document_id: str, accept: str | None = None
    ) -> httpx.Response:
        """``GET /v1/{resource}/{id}/file``. One API call.

        The rendered document itself. Verified 2026-08-21: the body is the
        PDF and ``Content-Disposition`` carries the document's own name. A
        bookkeeping voucher answers this path with 404, and a draft with 409.
        """
        return await self.download(f"/v1/{resource}/{document_id}/file", accept)

    async def document_meta(self, resource: str, document_id: str) -> dict[str, Any]:
        """``GET /v1/{resource}/{id}/document``. One API call.

        Returns the ``documentFileId`` under which the rendered document is
        filed. Verified 2026-08-21: that id through ``/v1/files/{id}`` yields
        byte-identical content, so the round trip buys nothing. A draft is
        refused with 406.
        """
        return _expect_object(
            await self.get_json(f"/v1/{resource}/{document_id}/document"), "document"
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
        response = await self.request(
            "POST",
            "/v1/files",
            files={"file": (filename, content, content_type)},
            data={"type": "voucher"},
        )
        return _expect_object(response.json(), "files")

    # -- internals --------------------------------------------------------

    async def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        """Wait before the next attempt, honouring Retry-After when present."""
        delay = min(BACKOFF_BASE * (2**attempt), BACKOFF_CAP)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                # A Retry-After can also be an HTTP date. Falling back to the
                # computed delay is better than failing to back off at all.
                logger.debug("Unparsable Retry-After: %r", retry_after)
        # Jitter, so that several waiters do not resume in lockstep.
        await self._sleep(delay * (0.5 + random.random() / 2))

    def _client_error(
        self, response: httpx.Response, method: str, path: str
    ) -> Exception:
        status = response.status_code
        body = _json_object(response)
        detail = _detail_text(body)
        sources = _issue_sources(body)

        if status == 401:
            return AuthError(
                "The API rejected the key. Check LXO_MCP_API_KEY, and that the "
                "key is still active in Lexware Office under Extensions, "
                "Public API."
            )
        if status == 403:
            return AuthError(
                f"The key is not permitted to {method} {path}. Check the "
                f"permissions the key was created with.{detail}"
            )
        if status == 404:
            return NotFoundError(f"{path}{detail}")
        # A stale `version` arrives as 406 naming `version`, not as 409
        # (verified 2026-08-20 by updating a contact with the version it had
        # before an earlier update), and a 409 need not be about a version at
        # all: downloading a sales document that is still a draft is refused
        # with one (verified 2026-08-21). So "read it again" is advice only
        # where a version was actually named, and every other conflict says
        # what it is without guessing why.
        if status == 406 and "version" in sources:
            return ConflictError(
                "The record changed since it was read. Read it again to get "
                f"the current version, then retry.{detail}"
            )
        if status == 409:
            return ConflictError(
                f"The API refused {method} {path} in this record's current "
                f"state.{detail}"
            )
        if status == 406:
            return ValidationError(
                f"The API refused {method} {path}. The request is either not "
                f"valid or not allowed in this record's current state.{detail}"
            )
        return ValidationError(f"The API rejected {method} {path}.{detail}")


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
