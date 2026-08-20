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
from .config import Settings
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
    ) -> httpx.Response:
        """Perform one API call, with rate limiting, retries and error mapping."""
        method = method.upper()
        retryable = method in RETRYABLE_METHODS
        headers = {"Authorization": f"Bearer {self.settings.require_api_key()}"}
        last_attempt = MAX_ATTEMPTS - 1

        for attempt in range(MAX_ATTEMPTS):
            await self._bucket.acquire()
            try:
                response = await self._http.request(
                    method, path, params=params, json=json, headers=headers
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
        payload = await self.get_json("/v1/profile")
        if not isinstance(payload, dict):
            raise UpstreamError("The profile endpoint returned an unexpected shape.")
        return payload

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
        detail = self._detail(response)

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
            return NotFoundError("resource", path.rsplit("/", 1)[-1])
        if status == 409:
            return ConflictError(
                "The record changed since it was read, or it is locked. Read it "
                f"again to get the current version, then retry.{detail}"
            )
        if status == 406:
            return ValidationError(
                "The API refused the action in the record's current state, for "
                "example pursuing a document that is still a draft."
                f"{detail}"
            )
        return ValidationError(f"The API rejected {method} {path}.{detail}")

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        """Pull the API's own error text out, without ever echoing the key."""
        try:
            body = response.json()
        except ValueError:
            return ""
        if not isinstance(body, dict):
            return ""
        parts = [str(body[key]) for key in ("errorCode", "message") if body.get(key)]
        issues = body.get("IssueList")
        if isinstance(issues, list):
            parts.extend(
                str(issue.get("source", "") or issue.get("type", ""))
                for issue in issues
                if isinstance(issue, dict)
            )
        text = " ".join(part for part in parts if part).strip()
        return f" {text}" if text else ""


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
