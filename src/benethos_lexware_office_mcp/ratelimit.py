"""The shared token bucket.

The Lexware API allows 2 requests per second, enforced with a token bucket
**across all endpoints at once** rather than per endpoint. One bucket per
process therefore, owned by the client and shared by every request whatever
resource it targets. A per-resource limiter would let several idle endpoints
each hand out a bucket worth of tokens and blow the global budget while every
one of them believed it was well behaved.

Both sides run the same algorithm and differ only in the penalty. Lexware
**polices**: a non-conformant request is dropped with 429 and, in the words of
the documentation, "the actual call will not be performed". This bucket
**shapes**: a non-conformant request waits until enough tokens have
accumulated, then goes out. That is why the local bucket has to be at least as
strict as the remote one — a request our shaper lets through early is a request
their policer destroys.

See SPECS.md section 10.1.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

__all__ = ["TokenBucket"]

Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]


class TokenBucket:
    """A token bucket that delays rather than drops.

    ``rate`` tokens are added per second up to ``capacity``. Tokens are
    recomputed from elapsed time on each acquisition, so an idle bucket costs
    nothing and there is no timer to keep alive.

    ``clock`` and ``sleep`` are injectable so the suite can run against
    virtual time instead of waiting in real seconds. The clock must be
    **monotonic**: an NTP correction or a daylight-saving step must not be
    able to hand out free tokens or stall the server for an hour.
    """

    def __init__(
        self,
        rate: float,
        capacity: int,
        *,
        clock: Clock | None = None,
        sleep: Sleeper | None = None,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be greater than zero")
        if capacity < 1:
            raise ValueError("capacity must be at least one")
        self.rate = rate
        self.capacity = capacity
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        # A full bucket at startup, so the first call is not delayed.
        self._tokens = float(capacity)
        self._updated = self._clock()
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    @property
    def tokens(self) -> float:
        """Tokens available as of the last acquisition. For tests and logging."""
        return self._tokens

    def _refill(self) -> float:
        now = self._clock()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._updated = now
        return now

    async def acquire(self, tokens: int = 1) -> None:
        """Wait until ``tokens`` are available, then spend them.

        The lock is held across the wait, so waiters are served in arrival
        order and a chatty caller cannot starve a quiet one. The wait is
        awaited rather than slept, so the server keeps answering other traffic
        while a call is queued.
        """
        if tokens < 1:
            raise ValueError("tokens must be at least one")
        if tokens > self.capacity:
            raise ValueError(
                f"cannot acquire {tokens} tokens from a bucket of capacity "
                f"{self.capacity}: the wait would never end"
            )
        async with self._lock:
            while True:
                now = self._refill()
                if now < self._blocked_until:
                    await self._sleep(self._blocked_until - now)
                    continue
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                await self._sleep((tokens - self._tokens) / self.rate)

    def drain(self, cooldown: float) -> None:
        """Empty the bucket and hold it shut for ``cooldown`` seconds.

        The circuit breaker for repeated 429s. The documentation warns that a
        client which does not reduce its rate "will stay blocked permanently",
        so backing off harder is the one response that can turn a transient
        problem into a dead API key.
        """
        self._refill()
        self._tokens = 0.0
        self._blocked_until = self._clock() + max(cooldown, 0.0)
