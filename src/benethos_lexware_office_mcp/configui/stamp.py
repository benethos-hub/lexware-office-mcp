"""When something was written, to the finest resolution that is not invented.

ISO 8601 with microseconds and the local UTC offset. The offset matters here
because a configuration bundle is made to travel: two machines in two time
zones comparing bare local times would order them wrongly.

**Nanoseconds are not offered, and the reason is measured rather than
assumed.** ``time.time_ns()`` reports in nanosecond units, but on this
platform the wall clock behind it advances in steps of about a millisecond -
200,000 calls in a row produced nine distinct values, and every one of them
ended in a fixed sub-microsecond remainder. Windows raises and lowers that
resolution depending on what else is running, so it can be coarser still.
Nine digits would therefore be six digits of clock and three of decoration,
and a timestamp that looks more exact than the clock it came from is worse
than a shorter one: somebody eventually relies on the difference.

Microseconds are what ``datetime`` holds and what the standard library can
read back, so that is where this stops.
"""

from __future__ import annotations

from datetime import datetime

__all__ = ["now"]


def now() -> str:
    """The current local time, for example ``2026-08-21T22:32:12.376638+02:00``."""
    return datetime.now().astimezone().isoformat(timespec="microseconds")
