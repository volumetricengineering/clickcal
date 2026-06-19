"""A thin async client for the parts of the ClickUp API we need."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

API_BASE = "https://api.clickup.com/api/v2"


@dataclass(frozen=True)
class ClickUpList:
    """A ClickUp list, with enough context to filter it out by id or name."""

    id: str
    name: str


@dataclass(frozen=True)
class Task:
    """A normalized ClickUp task ready to be turned into a calendar event."""

    id: str
    name: str
    description: str
    url: str
    status: str
    list_name: str
    start: datetime | None
    due: datetime | None
    # Whether the corresponding date carries a meaningful time-of-day. When
    # False, ClickUp stored an all-day date and the event should be all-day.
    start_has_time: bool = False
    due_has_time: bool = False
    # Formatted address from a ClickUp "location" custom field, if any.
    location: str = ""


def _parse_location(custom_fields: object) -> str:
    """Return the formatted address of the first populated location field.

    ClickUp has no built-in task location, but a custom field of type
    ``location`` carries a ``formatted_address``. We surface the first one that
    has a value so it can be shown in the event (handy for venue info / links).
    """
    if not isinstance(custom_fields, list):
        return ""
    for field in custom_fields:
        if not isinstance(field, dict) or field.get("type") != "location":
            continue
        value = field.get("value")
        if isinstance(value, dict):
            address = value.get("formatted_address")
            if address:
                return str(address)
    return ""


def _parse_ms(value: object) -> datetime | None:
    """Convert a ClickUp millisecond timestamp (string or int) to a datetime."""
    if value in (None, "", 0, "0"):
        return None
    try:
        millis = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)


class ClickUpClient:
    """Minimal ClickUp REST client scoped to listing lists and tasks."""

    def __init__(self, token: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=API_BASE,
            headers={"Authorization": token},
            timeout=30.0,
        )

    async def __aenter__(self) -> "ClickUpClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, **params: object) -> dict:
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_space_lists(self, space_id: str) -> list[ClickUpList]:
        """Return every active list in a space: folderless plus folder lists.

        Archived folders and archived lists are excluded. We both pass
        ``archived=false`` to the API and check each object's ``archived`` flag,
        since a folder's embedded ``lists`` array can still include archived
        child lists.
        """
        lists: list[ClickUpList] = []

        folderless = await self._get(f"/space/{space_id}/list", archived="false")
        for raw in folderless.get("lists", []):
            if not raw.get("archived"):
                lists.append(ClickUpList(id=str(raw["id"]), name=raw["name"]))

        folders = await self._get(f"/space/{space_id}/folder", archived="false")
        for folder in folders.get("folders", []):
            if folder.get("archived"):
                continue
            for raw in folder.get("lists", []):
                if not raw.get("archived"):
                    lists.append(ClickUpList(id=str(raw["id"]), name=raw["name"]))

        return lists

    async def get_list_tasks(
        self,
        list_: ClickUpList,
        *,
        include_closed: bool = False,
        include_subtasks: bool = True,
    ) -> list[Task]:
        """Fetch all (paginated) tasks for a single list."""
        tasks: list[Task] = []
        page = 0
        while True:
            data = await self._get(
                f"/list/{list_.id}/task",
                page=page,
                archived="false",
                include_closed="true" if include_closed else "false",
                subtasks="true" if include_subtasks else "false",
            )
            raw_tasks = data.get("tasks", [])
            for raw in raw_tasks:
                tasks.append(
                    Task(
                        id=str(raw["id"]),
                        name=raw.get("name", ""),
                        description=raw.get("description") or "",
                        url=raw.get("url", ""),
                        status=(raw.get("status") or {}).get("status", ""),
                        list_name=list_.name,
                        start=_parse_ms(raw.get("start_date")),
                        due=_parse_ms(raw.get("due_date")),
                        start_has_time=bool(raw.get("start_date_time")),
                        due_has_time=bool(raw.get("due_date_time")),
                        location=_parse_location(raw.get("custom_fields")),
                    )
                )
            # ClickUp signals the final page with last_page=true (or a short page).
            if data.get("last_page") or not raw_tasks:
                break
            page += 1

        return tasks
