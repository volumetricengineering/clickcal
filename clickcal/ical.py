"""Turn ClickUp tasks into an iCalendar feed."""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event

from .clickup import ClickUpList, Task

# Default duration applied to a timed task that has a start but no due date.
DEFAULT_DURATION = timedelta(hours=1)


def _is_timed(task: Task, tz: tzinfo) -> bool:
    """Whether a task should be a timed event rather than all-day.

    ClickUp's API returns null for its all-day flags, so we infer it from the
    dates. A task is treated as *timed* only when it has both a start and a due
    that fall on the same local day and span less than a full day (e.g. a 2-hour
    meeting). Multi-day ranges, single-point dates, and due-only tasks are
    treated as all-day conference/deadline entries.

    An explicit ClickUp time flag (when present) always forces a timed event.
    """
    if task.start_has_time or task.due_has_time:
        return True
    if task.start is None or task.due is None:
        return False

    start = task.start.astimezone(tz)
    due = task.due.astimezone(tz)
    if start.date() != due.date():
        return False
    # Same day: timed only if there is an actual (sub-day) duration.
    return due > start


def _add_event_times(event: Event, task: Task, tz: tzinfo) -> None:
    """Add DTSTART/DTEND to ``event``, all-day or timed as appropriate."""
    start_dt = task.start or task.due
    assert start_dt is not None  # guaranteed by the caller

    if not _is_timed(task, tz):
        # iCal all-day events use DATE values with an exclusive end date.
        start_date = start_dt.astimezone(tz).date()
        end_date = task.due.astimezone(tz).date() if task.due is not None else start_date
        event.add("dtstart", start_date)
        event.add("dtend", end_date + timedelta(days=1))
        return

    start = start_dt.astimezone(tz)
    if task.start is None and task.due is not None:
        # Due-only timed task: a short block ending at the due time.
        end = task.due.astimezone(tz) + DEFAULT_DURATION
    elif task.due is not None:
        end = task.due.astimezone(tz)
    else:
        end = start + DEFAULT_DURATION

    event.add("dtstart", start)
    event.add("dtend", end)


def filter_lists(
    lists: list[ClickUpList], excluded: list[str]
) -> list[ClickUpList]:
    """Drop lists whose id or (case-insensitive) name is in ``excluded``."""
    excluded_ids = {item for item in excluded}
    excluded_names = {item.casefold() for item in excluded}
    return [
        lst
        for lst in lists
        if lst.id not in excluded_ids and lst.name.casefold() not in excluded_names
    ]


def build_calendar(tasks: list[Task], *, name: str, timezone: str = "UTC") -> bytes:
    """Build an iCal feed from tasks that have a usable date.

    Tasks with neither a start nor a due date are skipped, since a calendar
    event needs at least one point in time. ``timezone`` is the IANA name of the
    ClickUp workspace timezone, used to recognize all-day dates and to render
    timed events in their local zone.
    """
    tz = ZoneInfo(timezone)

    cal = Calendar()
    cal.add("prodid", "-//clickcal//ClickUp iCal feed//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", name)

    for task in tasks:
        if task.start is None and task.due is None:
            continue

        event = Event()
        event.add("uid", f"{task.id}@clickup")
        event.add("summary", task.name)

        _add_event_times(event, task, tz)

        # Lead with the task's own content (description, then location) so
        # things like Zoom links sit at the top of the event details.
        description_parts = []
        if task.description:
            description_parts.append(task.description)
        if task.location:
            description_parts.append(task.location)
        if task.list_name:
            description_parts.append(f"List: {task.list_name}")
        if task.status:
            description_parts.append(f"Status: {task.status}")
        if task.url:
            description_parts.append(task.url)
        if description_parts:
            event.add("description", "\n\n".join(description_parts))

        if task.location:
            event.add("location", task.location)

        if task.url:
            event.add("url", task.url)

        cal.add_component(event)

    return cal.to_ical()
