"""The configuration interface, a process of its own.

It keeps no request log: a page only the local machine can reach, used by one
person, would log that person clicking. What it writes down is what changed -
the key, the token, a setting, the permissions, a profile - and what it
refused, so that whoever changed the key or switched on a writing tool left
a trace on stderr. Never the key or the token themselves, and never a
setting's value: the names say what changed, the file says to what.

**One line carries a secret, on purpose**: the address with the start code,
since handing the code to the person who started the process is what the
line is for. The code lives as long as the process does, and no other line
carries it.

These lines are English like every other line on stderr. The German of this
interface is for its pages.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from ._describe import describe
from .output import PACKAGE

__all__ = [
    "bound_beyond_loopback",
    "editing",
    "interrupted",
    "key_refused",
    "key_saved",
    "policy_saved",
    "port_taken",
    "profile_deleted",
    "profile_saved",
    "profiles_unreadable",
    "request_refused",
    "serving",
    "settings_saved",
    "signed_in",
    "stopped_from_page",
    "token_saved",
    "write_failed",
]

_log = logging.getLogger(f"{PACKAGE}.configui")


def serving(host: str, port: int, code: str) -> None:
    """The address to open, start code included.

    At WARNING so that no log level hides it: without this line the pages
    cannot be opened, the way a generated bearer token is said at WARNING
    because a client cannot connect without it.
    """
    _log.warning(
        "Configuration interface at http://%s:%s/?code=%s - "
        "stop it with Ctrl+C or Beenden on the page",
        host,
        port,
        code,
    )


def editing(kind: str, path: Path) -> None:
    """One of the three files this interface writes, pinned at its start."""
    _log.info("Editing the %s file %s", kind, path)


def bound_beyond_loopback(host: str) -> None:
    _log.warning(
        "Bound to %s, so the pages are reachable from outside this machine. "
        "The start code travels in the clear over HTTP: whoever reaches this "
        "port and reads along can open the pages and change the key. Outside "
        "a container start it with --host 127.0.0.1 only.",
        host,
    )


def port_taken(host: str, port: int, error: BaseException) -> None:
    _log.error(
        "Could not open %s:%s: %s. Is the interface running already? "
        "Otherwise pick another port with --port.",
        host,
        port,
        describe(error),
    )


def interrupted() -> None:
    """Ctrl+C, which this command catches itself."""
    _log.info("Stopped by an interrupt")


def stopped_from_page() -> None:
    """Beenden on a page, after the answer went out."""
    _log.info("Stopped from the page")


def profiles_unreadable(path: Path, error: BaseException) -> None:
    _log.warning("Unreadable profiles at %s: %s", path, describe(error))


def key_saved(file: str, checked: bool) -> None:
    how = "checked against the account first" if checked else "without a check"
    _log.info("API key written to %s, %s", file, how)


def key_refused() -> None:
    _log.warning("API key not saved: the account refused it")


def token_saved(file: str, generated: bool) -> None:
    how = "generated and written" if generated else "written"
    _log.info("Bearer token %s to %s", how, file)


def settings_saved(file: str, keys: Sequence[str]) -> None:
    _log.info(
        "%d setting%s written to %s: %s",
        len(keys),
        "" if len(keys) == 1 else "s",
        file,
        ", ".join(sorted(keys)),
    )


def policy_saved(path: Path, enabled: int, total: int, writers: Sequence[str]) -> None:
    """The one action here that changes what a server may do."""
    if writers:
        _log.warning(
            "Tool policy %s written, %d of %d tools on, %d of them able to "
            "change real accounting records: %s",
            path,
            enabled,
            total,
            len(writers),
            ", ".join(sorted(writers)),
        )
    else:
        _log.info(
            "Tool policy %s written, %d of %d tools on, all read-only",
            path,
            enabled,
            total,
        )


def profile_saved(profile: str, enabled: int, replaced: bool) -> None:
    how = "overwritten" if replaced else "created"
    _log.info(
        "Profile %r %s with %d tool%s",
        profile,
        how,
        enabled,
        "" if enabled == 1 else "s",
    )


def profile_deleted(profile: str) -> None:
    _log.info("Profile %r deleted", profile)


def write_failed(path: Path, error: BaseException) -> None:
    _log.warning("Could not write %s: %s", path, describe(error))


def request_refused(check: str) -> None:
    """A request turned away by one of the guards: host, origin, token, size,
    or the start code."""
    _log.warning("Request refused by the %s check", check)


def signed_in() -> None:
    """A browser gave the start code. Never the code itself."""
    _log.info("A browser signed in with the start code")
