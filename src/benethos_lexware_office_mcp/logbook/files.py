"""Downloads on disk, and uploads fetched from a URL.

The tool line already says what was downloaded and how large it was. What it
cannot say is that nothing new was written, or that older downloads were
deleted to keep the directory at its bound. A download's name is the
document's own and often the customer's, and its path is this machine's, so
neither is in a line. Nor can it say that the clients were told the list of
downloads grew, which a line here does by their number, or that telling
them failed while the download itself was answered.

Nor can it say where an upload was fetched from. A line here does, by scheme
and host alone: a signed link carries its key in the path or the query, and
the link is as good as the key for as long as it lives. The host is one
``LXO_MCP_UPLOAD_URLS`` names. A URL outside the setting is refused before
anything is sent, and its line says so by the scheme alone: its host was
chosen by the model, and a host name can carry any text a prompt put there.
"""

from __future__ import annotations

import logging

from ._describe import describe
from .output import PACKAGE

__all__ = [
    "fetched",
    "list_changed",
    "none_allowed",
    "not_a_url",
    "not_allowed",
    "not_announced",
    "not_fetched",
    "pruned",
    "reused",
]

_log = logging.getLogger(f"{PACKAGE}.storage")
# An upload's URL is not the download directory, and a person reading the
# log for one should not have to read past the other.
_fetch = logging.getLogger(f"{PACKAGE}.fetch")


def reused(size: int) -> None:
    _log.debug("An identical download of %d bytes was on disk, reused it", size)


def pruned(count: int, kept: int) -> None:
    _log.info("Deleted %d older downloads, the newest %d are kept", count, kept)


def list_changed(clients: int) -> None:
    _log.info("The download list changed, %d clients told", clients)


def not_announced(error: BaseException) -> None:
    _log.warning(
        "A download was answered, but the clients could not be told the list "
        "changed: %s",
        describe(error),
    )


def fetched(scheme: str, host: str, size: int, ms: float) -> None:
    _fetch.info(
        "Fetched %d bytes to upload from %s://%s in %.0f ms", size, scheme, host, ms
    )


def none_allowed() -> None:
    _fetch.warning(
        "Refused to fetch an upload: LXO_MCP_UPLOAD_URLS allows no address, "
        "nothing was requested"
    )


def not_a_url(scheme: str) -> None:
    _fetch.warning(
        "Refused to fetch an upload over %s: not a URL that can be fetched, "
        "nothing was requested",
        scheme,
    )


def not_allowed(scheme: str) -> None:
    _fetch.warning(
        "Refused to fetch an upload over %s: the address is outside "
        "LXO_MCP_UPLOAD_URLS, nothing was requested",
        scheme,
    )


def not_fetched(scheme: str, host: str, error: BaseException) -> None:
    _fetch.warning(
        "Fetching an upload from %s://%s failed: %s", scheme, host, describe(error)
    )
