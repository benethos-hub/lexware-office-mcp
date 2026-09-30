"""Downloads on disk.

The tool line already says what was downloaded and how large it was. What it
cannot say is that nothing new was written, which is the one thing about
the download directory worth knowing while it has no bound. A download's
name is the document's own and often the customer's, and its path is
this machine's, so neither is in a line.
"""

from __future__ import annotations

import logging

from .output import PACKAGE

__all__ = ["reused"]

_log = logging.getLogger(f"{PACKAGE}.storage")


def reused(size: int) -> None:
    _log.debug("An identical download of %d bytes was on disk, reused it", size)
