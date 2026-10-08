"""The mechanics of talking to the Lexware Office API.

Nothing else in this package talks to the network. A connection owns the
single shared token bucket, decides what may be retried, and maps every
upstream status onto a ``ToolError``. The endpoints themselves are
``client.LexwareClient``, which is one of these.

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
from typing import Any, Self

import httpx

from .. import __version__, logbook
from ..errors import ConflictError, RateLimitError, UpstreamError
from ..settings import Settings
from .ratelimit import Sleeper, TokenBucket
from .refusal import from_response

__all__ = ["BREAKER_THRESHOLD", "Connection"]

# PUT and DELETE are idempotent, and an update additionally carries the
# `version` it read: if the first attempt succeeded the version has moved on
# and a retry is refused as stale - 406 or 409, by resource - rather than
# applying the change twice. `_own_change` says which attempt moved it.
RETRYABLE_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE"})

# The methods whose failure leaves nothing to find out. Any other one that ends
# without an answer may have changed a record, retried or not: the last
# attempt can have been carried out as well as an earlier one.
READ_METHODS = frozenset({"GET", "HEAD"})

MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.5
BACKOFF_CAP = 8.0

# Consecutive 429s across requests before the bucket is held shut. Backing off
# harder is what turns a transient limit into a permanently blocked key.
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN = 30.0


class Connection:
    """One connection pool and one token bucket, and the rules for using them.

    One instance per server process. Every request goes through
    :meth:`request`, so the limiter and the retry rules apply to all of them.
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

    async def __aenter__(self) -> Self:
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
        writes = method not in READ_METHODS
        headers = {"Authorization": f"Bearer {self.settings.require_api_key()}"}
        if accept is not None:
            headers["Accept"] = accept
        # Whether an earlier attempt may have been carried out: it timed out,
        # lost its connection or got a 5xx. A 429 is certain not to have been.
        maybe_done = False

        for attempt in range(MAX_ATTEMPTS):
            more = attempt < MAX_ATTEMPTS - 1
            # RequestError rather than TransportError: an answer whose body
            # cannot be decoded, or a redirect loop, is not a transport error
            # and escaped as a crash - on a POST without saying the outcome
            # is unknown. A timeout is one of them.
            try:
                response = await self._send(
                    method,
                    path,
                    attempt,
                    headers=headers,
                    params=params,
                    json=json,
                    files=files,
                    data=data,
                )
            except httpx.RequestError as exc:
                # Not a 429, so the streak the breaker counts is over. Left
                # standing, two 429s either side of a timeout would trip it.
                self._consecutive_429 = 0
                if retryable and more:
                    maybe_done = True
                    await self._retry(method, path, attempt, error=exc)
                    continue
                raise _unanswered(method, path, exc, writes) from exc

            status = response.status_code
            if status == 429:
                # Safe to repeat for any method: the call was not performed.
                self._count_429()
                if more:
                    await self._retry(
                        method,
                        path,
                        attempt,
                        status=status,
                        retry_after=response.headers.get("Retry-After"),
                    )
                    continue
                raise RateLimitError(
                    "Rate limited. Retrying did not clear it, try again shortly."
                )

            self._consecutive_429 = 0

            if status >= 500:
                if retryable and more:
                    maybe_done = True
                    await self._retry(method, path, attempt, status=status)
                    continue
                failed = UpstreamError(
                    f"The API returned {status} for {method} {path}.",
                    outcome_unknown=writes,
                )
                failed.status = status
                raise failed

            return _answered(response, method, path, maybe_done=maybe_done)

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

    async def download(self, path: str, accept: str | None = None) -> httpx.Response:
        """GET something that comes back as bytes rather than JSON.

        The response is returned whole, because a caller needs the body, the
        content type and the filename the server suggested, and only the
        response carries all three.
        """
        return await self.request("GET", path, accept=accept)

    # -- internals --------------------------------------------------------

    async def _send(
        self,
        method: str,
        path: str,
        attempt: int,
        *,
        headers: dict[str, str],
        **content: Any,
    ) -> httpx.Response:
        """One attempt: through the bucket, onto the wire, into the log.

        An attempt that gets no answer is logged here and raised to the loop,
        which decides whether another follows.
        """
        number = attempt + 1
        queued_at = time.perf_counter()
        await self._bucket.acquire()
        logbook.tally.api_call()
        sent_at = time.perf_counter()
        queued = (sent_at - queued_at) * 1000
        try:
            response = await self._http.request(
                method, path, headers=headers, **content
            )
        except httpx.RequestError as exc:
            logbook.api.unanswered(method, path, exc, _since(sent_at), number)
            raise
        logbook.api.answered(
            method, path, response.status_code, _since(sent_at), number, queued
        )
        return response

    def _count_429(self) -> None:
        """Count one more 429 in a row, and trip the breaker at the threshold."""
        self._consecutive_429 += 1
        if self._consecutive_429 < BREAKER_THRESHOLD:
            return
        self._bucket.drain(BREAKER_COOLDOWN)
        logbook.api.breaker_tripped(self._consecutive_429, BREAKER_COOLDOWN)
        self._consecutive_429 = 0
        raise RateLimitError(
            "Rate limited repeatedly. Pausing for "
            f"{BREAKER_COOLDOWN:.0f} seconds. The Lexware limit of "
            "2 requests per second covers your whole account, so "
            "another client may be spending it too."
        )

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


def _unanswered(
    method: str, path: str, exc: httpx.RequestError, writes: bool
) -> UpstreamError:
    """The last attempt got no answer, and none follows."""
    if isinstance(exc, httpx.TimeoutException):
        what = "timed out"
    else:
        what = f"could not be completed: {exc}"
    return UpstreamError(f"{method} {path} {what}.", outcome_unknown=writes)


def _answered(
    response: httpx.Response, method: str, path: str, *, maybe_done: bool
) -> httpx.Response:
    """A final answer below 500 and not a 429: returned, or mapped to an error."""
    status = response.status_code
    if status == 404 and method == "DELETE" and maybe_done:
        # The retry of a delete finding nothing is the delete having
        # worked: the attempt whose answer was lost removed it.
        # Reporting 404 would tell the caller the record never
        # existed, right after this call destroyed it.
        return response
    if status == 401:
        logbook.api.key_rejected()
    if status < 400:
        return response
    refused = from_response(response, method, path)
    # Only a write can have moved the record. A read that is refused after
    # a lost answer - a draft's file, say - is refused for its own reasons.
    if maybe_done and method not in READ_METHODS and isinstance(refused, ConflictError):
        raise _own_change(refused, method, path)
    raise refused


def _own_change(refused: ConflictError, method: str, path: str) -> ConflictError:
    """A conflict on a retry, which the first attempt most likely caused.

    An update is retried after an attempt that got no answer, carrying the
    version it was written against. If that attempt was carried out, the
    record has moved to the next version, and the retry is refused as
    stale. Saying somebody changed the record would send the caller to
    apply the same change a second time.
    """
    own = ConflictError(
        f"{method} {path} got no answer and was sent again, and the retry "
        "was refused because the record has moved on. The first attempt was "
        "most likely carried out. Read the record again and check whether it "
        "already carries the change before sending it again."
    )
    own.status, own.code = refused.status, refused.code
    return own


def _since(started: float) -> float:
    """Milliseconds since ``started``, a ``perf_counter`` reading."""
    return (time.perf_counter() - started) * 1000


def _backoff(attempt: int, retry_after: str | None = None) -> float:
    """How long to wait before the next attempt, Retry-After honoured."""
    delay = min(BACKOFF_BASE * (2**attempt), BACKOFF_CAP)
    # Jitter, so that several waiters do not resume in lockstep. On the
    # computed delay only: a Retry-After is the earliest the server wants to
    # hear again, and waking before it buys the next 429.
    delay *= 0.5 + random.random() / 2
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
    return delay
