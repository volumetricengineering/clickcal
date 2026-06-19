import asyncio

import pytest

from clickcal.cache import FeedCache


class Clock:
    """A controllable monotonic clock for deterministic TTL tests."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_caches_within_ttl():
    clock = Clock()
    cache = FeedCache(ttl=60, monotonic=clock)
    calls = 0

    async def build() -> bytes:
        nonlocal calls
        calls += 1
        return f"render-{calls}".encode()

    async def run():
        first = await cache.get(build)
        clock.now += 30  # still within TTL
        second = await cache.get(build)
        return first, second

    first, second = asyncio.run(run())
    assert first.body == b"render-1"
    assert second.body == b"render-1"  # reused, not rebuilt
    assert calls == 1


def test_refreshes_after_ttl():
    clock = Clock()
    cache = FeedCache(ttl=60, monotonic=clock)
    calls = 0

    async def build() -> bytes:
        nonlocal calls
        calls += 1
        return f"render-{calls}".encode()

    async def run():
        await cache.get(build)
        clock.now += 61  # past TTL
        return await cache.get(build)

    second = asyncio.run(run())
    assert second.body == b"render-2"
    assert calls == 2


def test_ttl_zero_disables_caching():
    clock = Clock()
    cache = FeedCache(ttl=0, monotonic=clock)
    calls = 0

    async def build() -> bytes:
        nonlocal calls
        calls += 1
        return b"x"

    async def run():
        await cache.get(build)
        await cache.get(build)

    asyncio.run(run())
    assert calls == 2  # never considered fresh


def test_concurrent_requests_trigger_single_build():
    clock = Clock()
    cache = FeedCache(ttl=60, monotonic=clock)
    calls = 0

    async def build() -> bytes:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)  # hold the lock so others pile up
        return b"render"

    async def run():
        results = await asyncio.gather(*(cache.get(build) for _ in range(10)))
        return results

    results = asyncio.run(run())
    assert calls == 1  # stampede collapsed to one build
    assert all(r.body == b"render" for r in results)


def test_serves_stale_on_error():
    clock = Clock()
    cache = FeedCache(ttl=60, monotonic=clock)
    state = {"fail": False, "calls": 0}

    async def build() -> bytes:
        state["calls"] += 1
        if state["fail"]:
            raise RuntimeError("ClickUp is down")
        return b"good"

    async def run():
        good = await cache.get(build)
        clock.now += 61  # expire so the next get tries to refresh
        state["fail"] = True
        stale = await cache.get(build)
        return good, stale

    good, stale = asyncio.run(run())
    assert good.body == b"good"
    assert stale.body == b"good"  # refresh failed -> served last good snapshot


def test_raises_when_no_snapshot_and_build_fails():
    cache = FeedCache(ttl=60)

    async def build() -> bytes:
        raise RuntimeError("ClickUp is down")

    async def run():
        return await cache.get(build)

    with pytest.raises(RuntimeError):
        asyncio.run(run())


def test_etag_is_stable_and_quoted():
    cache = FeedCache(ttl=60)

    async def build() -> bytes:
        return b"some ical body"

    snapshot = asyncio.run(cache.get(build))
    assert snapshot.etag.startswith('"') and snapshot.etag.endswith('"')
