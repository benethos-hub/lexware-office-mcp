"""The API calls themselves, one line per attempt.

These replace what httpx used to write, rather than merely silencing it: a
request line here names the method and the path, never the query, which is
where a search term travels.

The path is shown a segment at a time, and only what a path of this API is
made of: a resource name, which is a lowercase word, and an id, which is a
UUID. An id is the model's argument, and a model that put a name where an id
belongs would otherwise have written that name into the log. Anything else
is shown as ``~``.
"""

from __future__ import annotations

import logging
import re

from ._describe import UUID, describe
from .output import PACKAGE

__all__ = [
    "answered",
    "breaker_tripped",
    "key_rejected",
    "retry_after_honoured",
    "retry_after_too_long",
    "retry_after_unreadable",
    "retrying_error",
    "retrying_status",
    "unanswered",
]

_log = logging.getLogger(f"{PACKAGE}.client")

_WORD = re.compile(r"[a-z][a-z0-9-]*")


def _shown(endpoint: str) -> str:
    """The path, with every segment that is neither a word nor a UUID hidden."""
    return "/".join(
        part if not part or _WORD.fullmatch(part) or UUID.fullmatch(part) else "~"
        for part in endpoint.split("?", 1)[0].split("/")
    )


def answered(
    method: str, endpoint: str, status: int, ms: float, attempt: int, queued: float
) -> None:
    """Debug: one attempt and its status. ``queued`` is the wait for the bucket."""
    waited = f", {queued:.0f} ms queued first" if queued >= 1 else ""
    _log.debug(
        "%s %s %d in %.0f ms, attempt %d%s",
        method,
        _shown(endpoint),
        status,
        ms,
        attempt,
        waited,
    )


def unanswered(
    method: str, endpoint: str, error: BaseException, ms: float, attempt: int
) -> None:
    """Debug: an attempt that timed out or lost its connection."""
    _log.debug(
        "%s %s got no answer in %.0f ms, attempt %d: %s",
        method,
        _shown(endpoint),
        ms,
        attempt,
        describe(error),
    )


def retrying_status(
    method: str, endpoint: str, status: int, delay: float, attempt: int
) -> None:
    _log.warning(
        "%s %s answered %d, attempt %d follows in %.1f s",
        method,
        _shown(endpoint),
        status,
        attempt,
        delay,
    )


def retrying_error(
    method: str, endpoint: str, error: BaseException, delay: float, attempt: int
) -> None:
    _log.warning(
        "%s %s got no answer (%s), attempt %d follows in %.1f s",
        method,
        _shown(endpoint),
        describe(error),
        attempt,
        delay,
    )


def breaker_tripped(count: int, delay: float) -> None:
    _log.warning(
        "Rate limited %d times in a row, holding every request for %.0f s",
        count,
        delay,
    )


def key_rejected() -> None:
    _log.warning("The API rejected the key. Check LXO_MCP_API_KEY.")


def retry_after_honoured(delay: float) -> None:
    _log.debug("Retry-After asked for %.1f s", delay)


def retry_after_too_long(delay: float) -> None:
    _log.warning(
        "Retry-After asked for %s s, longer than a call waits, so it was not retried",
        delay,
    )


def retry_after_unreadable() -> None:
    """An HTTP date rather than seconds. The usual delay applies instead."""
    _log.debug("Retry-After was not a number of seconds, backing off as usual")
