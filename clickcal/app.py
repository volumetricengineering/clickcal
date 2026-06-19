"""HTTP service exposing the ClickUp tasks as an iCal feed."""

from __future__ import annotations

import asyncio
import secrets

import httpx
from fastapi import FastAPI, HTTPException, Request, Response

from .cache import FeedCache
from .ical import build_calendar, filter_lists
from .clickup import ClickUpClient
from .config import Settings, get_settings

app = FastAPI(title="clickcal", description="Serve ClickUp tasks as an iCal feed.")

# One shared snapshot of the rendered feed, refreshed on a TTL. Created on
# first request so the app can be imported without valid ClickUp credentials.
_feed_cache: FeedCache | None = None


def _get_cache(settings: Settings) -> FeedCache:
    global _feed_cache
    if _feed_cache is None:
        _feed_cache = FeedCache(settings.cache_ttl)
    return _feed_cache


async def generate_ical(settings: Settings) -> bytes:
    """Fetch tasks from the configured space and render the calendar."""
    async with ClickUpClient(settings.token) as client:
        lists = await client.get_space_lists(settings.space_id)
        included = filter_lists(lists, settings.excluded_lists)

        task_groups = await asyncio.gather(
            *(
                client.get_list_tasks(
                    lst,
                    include_closed=settings.include_closed,
                    include_subtasks=settings.include_subtasks,
                )
                for lst in included
            )
        )

    tasks = [task for group in task_groups for task in group]
    return build_calendar(
        tasks, name=settings.calendar_name, timezone=settings.timezone
    )


def _authorize(settings: Settings, token: str | None) -> None:
    """Enforce the feed token, if one is configured.

    Responds with 404 (not 401) on a missing/wrong token so the existence of a
    valid feed isn't revealed. The comparison is constant-time to avoid leaking
    the token through response timing.
    """
    if not settings.feed_token:
        return
    if token is None or not secrets.compare_digest(token, settings.feed_token):
        raise HTTPException(status_code=404, detail="Not Found")


async def _serve_feed(request: Request, settings: Settings) -> Response:
    cache = _get_cache(settings)

    try:
        snapshot = await cache.get(lambda: generate_ical(settings))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"ClickUp API returned {exc.response.status_code}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"ClickUp request failed: {exc}") from exc

    cache_control = f"max-age={int(settings.cache_ttl)}"
    # If the client already holds this exact render, skip resending the body.
    if request.headers.get("if-none-match") == snapshot.etag:
        return Response(
            status_code=304,
            headers={"ETag": snapshot.etag, "Cache-Control": cache_control},
        )

    return Response(
        content=snapshot.body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="clickup.ics"',
            "ETag": snapshot.etag,
            "Cache-Control": cache_control,
        },
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/calendar.ics")
async def calendar(request: Request) -> Response:
    settings = get_settings()
    # Without a configured token there is nothing to match here; if a token IS
    # configured, the unprotected path must not serve the feed.
    _authorize(settings, None)
    return await _serve_feed(request, settings)


@app.get("/calendar/{token}.ics")
async def calendar_with_token(request: Request, token: str) -> Response:
    settings = get_settings()
    _authorize(settings, token)
    return await _serve_feed(request, settings)
