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


class FeedCache:
    """Caches one rendered feed snapshot with a TTL and stampede protection."""

    def __init__(self, ttl: float, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl
        self._monotonic = monotonic
        self._lock = asyncio.Lock()
        self._snapshot: Snapshot | None = None
        self._fetched_at = 0.0

    def _is_fresh(self) -> bool:
        return (
            self._snapshot is not None
            and self._ttl > 0
            and self._monotonic() - self._fetched_at < self._ttl
        )

    async def get(self, build: Builder) -> Snapshot:
        """Return a fresh snapshot, rebuilding via ``build`` only when needed.

        A burst of concurrent callers triggers at most one ``build``; the rest
        wait on the lock and reuse the result. If ``build`` raises and a
        previous snapshot exists, that stale snapshot is returned instead.
        """
        if self._is_fresh():
            return self._snapshot  # type: ignore[return-value]

        async with self._lock:
            # Another caller may have refreshed while we waited for the lock.
            if self._is_fresh():
                return self._snapshot  # type: ignore[return-value]

            try:
                body = await build()
            except Exception:
                if self._snapshot is not None:
                    return self._snapshot  # serve stale rather than fail
                raise

            self._snapshot = Snapshot(body=body, etag=_etag(body))
            self._fetched_at = self._monotonic()
            return self._snapshot
