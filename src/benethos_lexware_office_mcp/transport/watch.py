"""Ending the process when its settings file changes.

Settings are read when the process starts and never again, so a change to
the file takes effect in a fresh process. Where something restarts this one
- a container, a service manager - the HTTP transport can be told to end on a
change and leave the rest to it. See SPECS.md section 6.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import logbook

__all__ = ["Snapshot", "snapshot", "watch_for_change"]

# How often the settings file is looked at. Slow enough to cost nothing, fast
# enough that a person who just saved the key does not wait for it.
CONFIG_POLL_SECONDS = 2.0


def _fingerprint(path: Path) -> str | None:
    """What the file says right now, or ``None`` while it does not exist.

    The content rather than the timestamp: the configuration interface writes
    the whole file on every save, and two saves inside one clock tick would
    look identical by mtime.
    """
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


@dataclass(frozen=True)
class Snapshot:
    """What the settings file said at one moment, for a watch to compare with."""

    digest: str | None


def snapshot(path: Path) -> Snapshot:
    """The file as it is now, taken before the settings are read from it.

    Before rather than after: a change landing in between then reads as one,
    and the process ends once more than it had to. Taken after, the same
    change would be the state the watch compares with, and a setting saved in
    the first seconds of a start would never reach the process.
    """
    return Snapshot(_fingerprint(path))


def watch_for_change(
    path: Path,
    on_change: Callable[[], None],
    *,
    stop: threading.Event,
    poll: float = CONFIG_POLL_SECONDS,
    ready: threading.Event | None = None,
    since: Snapshot | None = None,
) -> None:
    """Call ``on_change`` once the file differs from what the process read.

    Settings are read when the process starts and never again - the API key
    goes into a long-lived client, and the rate limiter that hangs off it is
    the one this process is allowed to have. Rebuilding that in place would
    mean moving state between two clients. Ending the process instead hands
    the problem to whatever started it, and a fresh one reads everything
    again. Nothing calls this unless something is there to restart it.

    ``since`` is the file as the settings were read from it, which is what a
    change is measured against. Without it the watch takes the file as it
    finds it, once two reads agree - two polls after the start, and a save in
    those seconds then became the baseline and never ended the process.

    ``ready`` is set once the file this is measured against has been read.
    Nothing in the server passes it: it exists so that a test can write to the
    file knowing the watch is already looking at it, rather than racing the
    thread it just started and calling whichever won a property of the code.
    """
    if since is not None:
        baseline = since.digest
    else:
        settled, baseline = _settled(path, stop=stop, poll=poll)
        if not settled:
            return
    if ready is not None:
        ready.set()
    while True:
        settled, current = _settled(path, stop=stop, poll=poll)
        if not settled:
            return
        if current != baseline:
            logbook.lifecycle.settings_changed(path.name)
            on_change()
            return


def _settled(
    path: Path, *, stop: threading.Event, poll: float
) -> tuple[bool, str | None]:
    """The file's content once it has stopped moving.

    Saving truncates before it writes, so a single read can catch an empty or
    half-written file and call it a state. Two reads in a row that agree is a
    state, a read that disagrees with the one before it is a save in progress.

    Both ends of the comparison need this. The interface rewrites the whole
    file on every save, changed or not, so the difference the watch looks for
    is often only the momentary emptiness in the middle of one - and a watch
    started while a save was in flight would otherwise take that emptiness as
    the baseline and end the process over the file coming back.

    Returns ``(False, None)`` when asked to stop, which is the only reason it
    gives up.
    """
    seen = _fingerprint(path)
    while not stop.wait(poll):
        again = _fingerprint(path)
        if again == seen:
            return True, seen
        seen = again
    return False, None
