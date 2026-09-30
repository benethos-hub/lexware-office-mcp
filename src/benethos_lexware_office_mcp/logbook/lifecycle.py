"""Starting, listening and ending: what the process is and may do.

The first lines anyone reads, and the ones that explain an empty tool list,
which a client shows without saying why.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from .output import PACKAGE

__all__ = [
    "ending_on_change",
    "interrupted",
    "listening",
    "no_policy",
    "reachable_from_outside",
    "settings_changed",
    "started",
    "token_generated",
    "tools_enabled",
]

_log = logging.getLogger(f"{PACKAGE}.server")


def started(version: str, transport: str) -> None:
    _log.info("%s started over %s", version, transport)


def no_policy(path: Path | None) -> None:
    _log.warning(
        "No tool policy at %s, so no tools are offered. Create one with "
        "--tools read-only, then enable what this account may be used for.",
        path,
    )


def tools_enabled(enabled: int, total: int, writers: Sequence[str], path: Path) -> None:
    """What this process may do. A warning as soon as it may write."""
    if writers:
        _log.warning(
            "%d of %d tools enabled, %d of them able to change real accounting "
            "records: %s. Per %s.",
            enabled,
            total,
            len(writers),
            ", ".join(sorted(writers)),
            path,
        )
    else:
        _log.info(
            "%d of %d tools enabled, all read-only. Per %s.", enabled, total, path
        )


def listening(transport: str, host: str, port: int, route: str) -> None:
    _log.info(
        "%s on http://%s:%s%s, bearer token required", transport, host, port, route
    )


def reachable_from_outside(host: str) -> None:
    _log.warning(
        "Bound to %s, so this port is reachable from outside this machine. "
        "In a container that is what the published port is for. Anywhere "
        "else, the bearer token is the only thing in the way.",
        host,
    )


def token_generated(file: str) -> None:
    """The token itself never: the configuration interface shows it."""
    _log.warning(
        "No bearer token was set, so one was generated and written to %s. "
        "The configuration interface shows it - a client needs it to connect.",
        file,
    )


def ending_on_change(file: str) -> None:
    _log.info("Ending on a change to %s", file)


def settings_changed(file: str) -> None:
    _log.info("%s changed, ending this process so it is started again", file)


def interrupted() -> None:
    """Ctrl+C, in place of the traceback it would otherwise end in."""
    _log.info("Stopped by an interrupt")
