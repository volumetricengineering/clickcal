from datetime import datetime, timezone

from clickcal.ical import build_calendar, filter_lists
from clickcal.clickup import ClickUpList, Task


def _task(**kwargs) -> Task:
    base = dict(
        id="abc",
        name="Do the thing",
        description="some details",
        url="https://app.clickup.com/t/abc",
        status="in progress",
        list_name="Work",
        start=datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc),
        due=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
        start_has_time=False,
        due_has_time=False,
    )
    base.update(kwargs)
    return Task(**base)  # type: ignore[arg-type]


def _lists():
    return [
        ClickUpList(id="1", name="Work"),
        ClickUpList(id="2", name="Backlog"),
        ClickUpList(id="3", name="Personal"),
    ]


def test_filter_lists_by_id_and_name():
    result = filter_lists(_lists(), ["2", "personal"])
    assert [lst.name for lst in result] == ["Work"]


def test_filter_lists_include_only_keeps_matches():
    # An include filter narrows the feed to just the named lists.
    result = filter_lists(_lists(), [], include=["Work", "Personal"])
    assert [lst.name for lst in result] == ["Work", "Personal"]


def test_filter_lists_include_matches_by_id_and_is_case_insensitive():
    result = filter_lists(_lists(), [], include=["2", "PERSONAL"])
    assert [lst.name for lst in result] == ["Backlog", "Personal"]


def test_filter_lists_empty_include_keeps_all():
    # The default (no include) keeps every list not otherwise excluded.
    result = filter_lists(_lists(), [], include=[])
    assert [lst.name for lst in result] == ["Work", "Backlog", "Personal"]


def test_filter_lists_exclude_drops_matches():
    result = filter_lists(_lists(), [], exclude=["backlog"])
    assert [lst.name for lst in result] == ["Work", "Personal"]


def test_filter_lists_configured_exclusion_always_applies():
    # A configured exclusion wins even if the request tries to include it.
    result = filter_lists(_lists(), ["Backlog"], include=["Work", "Backlog"])
    assert [lst.name for lst in result] == ["Work"]


def test_filter_lists_exclude_overrides_include():
    result = filter_lists(_lists(), [], include=["Work", "Personal"], exclude=["Personal"])
    assert [lst.name for lst in result] == ["Work"]


def test_build_calendar_emits_event():
    ical = build_calendar([_task()], name="Test").decode()
    assert "BEGIN:VEVENT" in ical
    assert "SUMMARY:Do the thing" in ical
    assert "UID:abc@clickup" in ical
    assert "X-WR-CALNAME:Test" in ical


def test_tasks_without_dates_are_skipped():
    ical = build_calendar([_task(start=None, due=None)], name="Test").decode()
    assert "BEGIN:VEVENT" not in ical


def test_timed_due_only_task_gets_an_end():
    # A timed deadline (flagged) becomes a short block ending at the due time.
    due = datetime(2026, 6, 21, 15, 0, tzinfo=timezone.utc)
    ical = build_calendar(
        [_task(start=None, due=due, due_has_time=True)],
        name="Test",
        timezone="UTC",
    ).decode()
    assert "BEGIN:VEVENT" in ical
    assert "DTSTART:20260621T150000" in ical
    assert "DTEND:20260621T160000" in ical


def test_same_day_block_is_timed():
    # Start and due on the same day with a real duration -> timed event.
    ical = build_calendar([_task()], name="Test", timezone="UTC").decode()
    assert "DTSTART;VALUE=DATE:" not in ical
    assert "T090000" in ical  # 09:00 start time present


def test_multi_day_range_is_all_day():
    # A range spanning several days (e.g. a conference) -> all-day event.
    start = datetime(2026, 6, 8, 2, 0, tzinfo=timezone.utc)
    due = datetime(2026, 6, 11, 2, 0, tzinfo=timezone.utc)
    ical = build_calendar(
        [_task(start=start, due=due)], name="Test", timezone="UTC"
    ).decode()
    assert "BEGIN:VEVENT" in ical
    assert "DTSTART;VALUE=DATE:20260608" in ical
    # End date is exclusive: the last day (11th) is included.
    assert "DTEND;VALUE=DATE:20260612" in ical
    assert "T0" not in ical


def test_single_point_date_is_all_day():
    # Start == due (no duration) -> a one-day all-day event.
    day = datetime(2026, 6, 17, 2, 0, tzinfo=timezone.utc)
    ical = build_calendar(
        [_task(start=day, due=day)], name="Test", timezone="UTC"
    ).decode()
    assert "DTSTART;VALUE=DATE:20260617" in ical
    assert "DTEND;VALUE=DATE:20260618" in ical


def test_due_only_is_all_day():
    # A deadline with no start -> all-day on the due date.
    due = datetime(2026, 10, 20, 2, 0, tzinfo=timezone.utc)
    ical = build_calendar(
        [_task(start=None, due=due)], name="Test", timezone="UTC"
    ).decode()
    assert "DTSTART;VALUE=DATE:20261020" in ical


def test_explicit_time_flag_forces_timed():
    # If ClickUp ever does report a time flag, honor it even for a single point.
    day = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    ical = build_calendar(
        [_task(start=day, due=day, start_has_time=True, due_has_time=True)],
        name="Test",
        timezone="UTC",
    ).decode()
    assert "DTSTART;VALUE=DATE:" not in ical


def test_exclude_multi_day_drops_multi_day_ranges():
    start = datetime(2026, 6, 8, 2, 0, tzinfo=timezone.utc)
    due = datetime(2026, 6, 11, 2, 0, tzinfo=timezone.utc)
    ical = build_calendar(
        [_task(start=start, due=due)],
        name="Test",
        timezone="UTC",
        exclude_multi_day=True,
    ).decode()
    assert "BEGIN:VEVENT" not in ical


def test_exclude_multi_day_keeps_single_day_events():
    # A same-day timed block is not multi-day and should survive the filter.
    ical = build_calendar(
        [_task()], name="Test", timezone="UTC", exclude_multi_day=True
    ).decode()
    assert "BEGIN:VEVENT" in ical


def test_exclude_multi_day_keeps_due_only_events():
    due = datetime(2026, 10, 20, 2, 0, tzinfo=timezone.utc)
    ical = build_calendar(
        [_task(start=None, due=due)],
        name="Test",
        timezone="UTC",
        exclude_multi_day=True,
    ).decode()
    assert "BEGIN:VEVENT" in ical


def test_multi_day_kept_by_default():
    start = datetime(2026, 6, 8, 2, 0, tzinfo=timezone.utc)
    due = datetime(2026, 6, 11, 2, 0, tzinfo=timezone.utc)
    ical = build_calendar([_task(start=start, due=due)], name="Test", timezone="UTC").decode()
    assert "BEGIN:VEVENT" in ical


def _description_of(ical: str) -> str:
    """Extract and unfold the single event DESCRIPTION value from an ICS string."""
    lines = ical.splitlines()
    out = []
    capturing = False
    for line in lines:
        if line.startswith("DESCRIPTION:"):
            out.append(line[len("DESCRIPTION:") :])
            capturing = True
        elif capturing and line.startswith(" "):
            out.append(line[1:])  # continuation line (leading space)
        elif capturing:
            break
    return "".join(out)


def test_description_leads_with_task_description_then_location():
    ical = build_calendar(
        [_task(description="Join Zoom: https://zoom.us/j/123", location="Berlin")],
        name="Test",
    ).decode()
    desc = _description_of(ical)
    # Description text comes first, location second, both ahead of List/Status.
    assert desc.index("zoom.us") < desc.index("Berlin")
    assert desc.index("Berlin") < desc.index("List: Work")


def test_location_when_no_description_is_first():
    ical = build_calendar(
        [_task(description="", location="Online via Zoom")],
        name="Test",
    ).decode()
    desc = _description_of(ical)
    assert desc.index("Online via Zoom") < desc.index("List: Work")


def test_location_sets_ical_location_property():
    ical = build_calendar([_task(location="Leipzig, Germany")], name="Test").decode()
    assert "LOCATION:Leipzig\\, Germany" in ical  # comma is escaped in iCal


def test_no_location_property_when_absent():
    ical = build_calendar([_task(location="")], name="Test").decode()
    assert "\nLOCATION:" not in ical and not ical.startswith("LOCATION:")
