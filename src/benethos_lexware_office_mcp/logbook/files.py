"""Downloads on disk, and uploads fetched from a URL.

The tool line already says what was downloaded and how large it was. What it
cannot say is that nothing new was written, or that older downloads were
deleted to keep the directory at its bound. A download's name is the
document's own and often the customer's, and its path is this machine's, so
neither is in a line.

Nor can it say where an upload was fetched from. A line here does, by scheme
and host alone: a signed link carries its key in the path or the query, and
the link is as good as the key for as long as it lives. The host is one
``LXO_MCP_UPLOAD_URLS`` names - a URL outside the setting is refused before
any line about it, and its host, which the model chose, is not written down.
"""

from __future__ import annotations

import logging

from ._describe import describe
from .output import PACKAGE

__all__ = ["fetched", "not_fetched", "pruned", "reused"]

_log = logging.getLogger(f"{PACKAGE}.storage")


def reused(size: int) -> None:
    _log.debug("An identical download of %d bytes was on disk, reused it", size)


def pruned(count: int, kept: int) -> None:
    _log.info("Deleted %d older downloads, the newest %d are kept", count, kept)


def fetched(scheme: str, host: str, size: int, ms: float) -> None:
    _log.info(
        "Fetched %d bytes to upload from %s://%s in %.0f ms", size, scheme, host, ms
    )


def not_fetched(scheme: str, host: str, error: BaseException) -> None:
    _log.warning(
        "Fetching an upload from %s://%s failed: %s", scheme, host, describe(error)
    )
