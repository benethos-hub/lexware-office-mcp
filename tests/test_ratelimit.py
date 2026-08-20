"""The shared token bucket, against virtual time.

Never against ``time.sleep``: the suite has to stay fast and deterministic,
and a limiter tested in real seconds is a limiter nobody runs.
"""

from __future__ import annotations

import asyncio

import pytest

from benethos_lexware_office_mcp.ratelimit import TokenBucket


class FakeClock:
    """A monotonic clock that only moves when something waits on it."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make(rate: float = 2.0, capacity: int = 2) -> tuple[TokenBucket, FakeClock]:
    clock = FakeClock()
    return TokenBucket(rate, capacity, clock=clock, sleep=clock.sleep), clock


async def test_a_full_bucket_lets_a_burst_through_without_waiting() -> None:
    bucket, clock = make(rate=2.0, capacity=2)
    await bucket.acquire()
    await bucket.acquire()
    assert clock.slept == []


async def test_beyond_the_burst_the_pace_falls_back_to_the_rate() -> None:
    bucket, clock = make(rate=2.0, capacity=2)
    for _ in range(2):
        await bucket.acquire()

    await bucket.acquire()

    # Two tokens spent, the third has to be waited for: 1 / rate seconds.
    assert clock.slept == [pytest.approx(0.5)]


async def test_refill_saturates_at_capacity() -> None:
    """An hour of idling must not buy an hour of tokens."""
    bucket, clock = make(rate=2.0, capacity=2)
    await bucket.acquire()
    await bucket.acquire()

    clock.advance(3600)

    await bucket.acquire()
    await bucket.acquire()
    assert clock.slept == []
    await bucket.acquire()
    assert clock.slept == [pytest.approx(0.5)]


async def test_a_non_conformant_request_is_delayed_and_never_dropped() -> None:
    """This bucket shapes. Lexware polices. That is the whole difference."""
    bucket, _ = make(rate=1.0, capacity=1)
    results = [await bucket.acquire() for _ in range(5)]
    assert results == [None] * 5


async def test_one_bucket_is_shared_across_different_endpoints() -> None:
    """A per-resource limiter would hand out one budget per resource."""
    bucket, clock = make(rate=2.0, capacity=2)

    async def call(_path: str) -> None:
        await bucket.acquire()

    await call("/v1/contacts")
    await call("/v1/invoices")
    await call("/v1/articles")

    assert clock.slept == [pytest.approx(0.5)]


async def test_concurrent_waiters_cannot_spend_the_same_token_twice() -> None:
    bucket, clock = make(rate=4.0, capacity=1)

    await asyncio.gather(*(bucket.acquire() for _ in range(4)))

    # One free, three waited a quarter second each.
    assert len(clock.slept) == 3
    assert bucket.tokens == pytest.approx(0.0)


async def test_drain_holds_the_bucket_shut_for_the_cooldown() -> None:
    bucket, clock = make(rate=2.0, capacity=2)

    bucket.drain(30.0)
    await bucket.acquire()

    assert clock.slept[0] == pytest.approx(30.0)


async def test_partial_tokens_are_kept() -> None:
    """The fluid formulation: half a token of progress is not thrown away."""
    bucket, clock = make(rate=2.0, capacity=2)
    await bucket.acquire()
    await bucket.acquire()
    clock.advance(0.25)

    await bucket.acquire()

    assert clock.slept == [pytest.approx(0.25)]


@pytest.mark.parametrize(("rate", "capacity"), [(0, 1), (-1, 1), (1, 0)])
def test_nonsense_parameters_are_rejected(rate: float, capacity: int) -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate, capacity)


async def test_asking_for_more_than_the_capacity_fails_fast() -> None:
    """Rather than waiting forever for tokens that can never accumulate."""
    bucket, _ = make(rate=2.0, capacity=2)
    with pytest.raises(ValueError):
        await bucket.acquire(3)


async def test_acquiring_zero_is_rejected() -> None:
    bucket, _ = make()
    with pytest.raises(ValueError):
        await bucket.acquire(0)


async def test_the_default_bucket_uses_a_monotonic_clock() -> None:
    """A wall clock could hand out free tokens on an NTP correction."""
    import time

    assert TokenBucket(1.0, 1)._clock is time.monotonic
