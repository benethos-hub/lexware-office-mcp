"""The API calls themselves, as the client makes them."""

from __future__ import annotations

import logging

from .output import PACKAGE

__all__ = ["retry_after_unreadable"]

_log = logging.getLogger(f"{PACKAGE}.client")


def retry_after_unreadable() -> None:
    """An HTTP date rather than seconds. The usual delay applies instead."""
    _log.debug("Retry-After was not a number of seconds, backing off as usual")
