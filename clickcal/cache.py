"""A small in-process TTL cache for the rendered iCal feed.

The feed is expensive to build (many ClickUp API calls) and is requested as a
whole by calendar clients that poll on their own schedule. This caches the
rendered bytes with a short TTL and:

* collapses a burst of concurrent requests into a single rebuild (stampede
  protection) via an ``asyncio.Lock``;
* serves the last good snapshot if a refresh fails, so a transient ClickUp
  outage degrades to "slightly stale" rather than an error.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

# A coroutine that builds the feed bytes when the cache needs to refresh.
Builder = Callable[[], Awaitable[bytes]]


@dataclass(frozen=True)
class Snapshot:
    """A cached feed render plus its ETag for HTTP conditional requests."""

    body: bytes
    etag: str


def _etag(body: bytes) -> str:
    """A short, stable ETag derived from the feed contents."""
    return f'"{hashlib.sha256(body).hexdigest()[:16]}"'


@dataclass
class _Entry:
    """The cached snapshot for one feed variant plus its own refresh lock."""

    lock: asyncio.Lock
    snapshot: Snapshot | None = None
    fetched_at: float = 0.0


class FeedCache:
    """Caches rendered feed snapshots with a TTL and stampede protection.

    Snapshots are keyed so that different feed variants (e.g. different
    include/exclude list filters) are cached independently. The default key of
    ``""`` covers the unfiltered feed.
    """

    def __init__(self, ttl: float, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl
        self._monotonic = monotonic
        self._entries: dict[str, _Entry] = {}

    def _entry(self, key: str) -> _Entry:
        entry = self._entries.get(key)
        if entry is None:
            entry = _Entry(lock=asyncio.Lock())
            self._entries[key] = entry
        return entry

    def _is_fresh(self, entry: _Entry) -> bool:
        return (
            entry.snapshot is not None
            and self._ttl > 0
            and self._monotonic() - entry.fetched_at < self._ttl
        )

    async def get(self, build: Builder, *, key: str = "") -> Snapshot:
        """Return a fresh snapshot for ``key``, rebuilding only when needed.

        A burst of concurrent callers for the same key triggers at most one
        ``build``; the rest wait on the lock and reuse the result. If ``build``
        raises and a previous snapshot exists, that stale snapshot is returned.
        """
        entry = self._entry(key)
        if self._is_fresh(entry):
            return entry.snapshot  # type: ignore[return-value]

        async with entry.lock:
            # Another caller may have refreshed while we waited for the lock.
            if self._is_fresh(entry):
                return entry.snapshot  # type: ignore[return-value]

            try:
                body = await build()
            except Exception:
                if entry.snapshot is not None:
                    return entry.snapshot  # serve stale rather than fail
                raise

            entry.snapshot = Snapshot(body=body, etag=_etag(body))
            entry.fetched_at = self._monotonic()
            return entry.snapshot
