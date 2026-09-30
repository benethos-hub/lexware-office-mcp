"""The configuration interface, a process of its own.

It keeps no request log: a page only the local machine can reach, used by one
person, would log that person clicking. What it writes down is what changed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ._describe import describe
from .output import PACKAGE

__all__ = ["profiles_unreadable"]

_log = logging.getLogger(f"{PACKAGE}.configui")


def profiles_unreadable(path: Path, error: BaseException) -> None:
    _log.warning("Unreadable profiles at %s: %s", path, describe(error))
