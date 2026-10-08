"""How many API calls one tool call made.

The client counts each attempt it sends, and the tool wrapper reads the count
when the tool returns. A context variable carries it between the two, so
tools running at the same time each count their own: every call runs in its
own task, and a task starts with a copy of the context it was made in.
Outside a tool call - the configuration interface testing a key - nothing is
counting, and a call counts for nobody.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator
from contextvars import ContextVar

__all__ = ["Tally", "api_call", "counting", "ms_since"]


class Tally:
    """The count for one tool call."""

    def __init__(self) -> None:
        self.calls = 0


_current: ContextVar[Tally | None] = ContextVar("lxo_api_calls", default=None)


@contextlib.contextmanager
def counting() -> Iterator[Tally]:
    """Count the API calls made until the block ends."""
    tally = Tally()
    token = _current.set(tally)
    try:
        yield tally
    finally:
        _current.reset(token)


def api_call() -> None:
    """One request is about to be sent."""
    tally = _current.get()
    if tally is not None:
        tally.calls += 1


def ms_since(started: float) -> float:
    """Milliseconds since ``started``, a ``perf_counter`` reading.

    How long a request or a tool call took, the figure every timed line
    reports, measured the same way on both sides.
    """
    return (time.perf_counter() - started) * 1000
