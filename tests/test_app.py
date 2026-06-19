import os

import pytest

os.environ.setdefault("CLICKCAL_TOKEN", "test-token")
os.environ.setdefault("CLICKCAL_SPACE_ID", "1")

from fastapi.testclient import TestClient

import clickcal.app as app_module
from clickcal.app import app


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    # The feed cache is a module-level singleton; clear it between tests.
    app_module._feed_cache = None
    yield
    app_module._feed_cache = None


@pytest.fixture
def client(monkeypatch):
    calls = {"n": 0}

    async def fake_generate(settings):
        calls["n"] += 1
        return b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"

    monkeypatch.setattr(app_module, "generate_ical", fake_generate)
    return TestClient(app), calls


def test_calendar_returns_ical(client):
    c, _ = client
    resp = c.get("/calendar.ics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/calendar")
    assert "ETag" in resp.headers
    assert resp.headers["Cache-Control"].startswith("max-age=")
    assert resp.content.startswith(b"BEGIN:VCALENDAR")


def test_second_request_is_served_from_cache(client):
    c, calls = client
    c.get("/calendar.ics")
    c.get("/calendar.ics")
    assert calls["n"] == 1  # only one upstream render


def test_conditional_request_returns_304(client):
    c, _ = client
    first = c.get("/calendar.ics")
    etag = first.headers["ETag"]
    second = c.get("/calendar.ics", headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["ETag"] == etag


def test_healthz(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}


def test_no_token_configured_serves_unprotected_path(client, monkeypatch):
    monkeypatch.delenv("CLICKCAL_FEED_TOKEN", raising=False)
    c, _ = client
    assert c.get("/calendar.ics").status_code == 200


def test_token_protects_unguessable_path(client, monkeypatch):
    monkeypatch.setenv("CLICKCAL_FEED_TOKEN", "s3cret-token")
    c, _ = client

    # The plain path is now hidden.
    assert c.get("/calendar.ics").status_code == 404
    # The correct token serves the feed.
    ok = c.get("/calendar/s3cret-token.ics")
    assert ok.status_code == 200
    assert ok.content.startswith(b"BEGIN:VCALENDAR")
    # A wrong token looks like nothing is there (404, not 401/403).
    assert c.get("/calendar/wrong-token.ics").status_code == 404


def test_healthz_stays_open_with_token(client, monkeypatch):
    monkeypatch.setenv("CLICKCAL_FEED_TOKEN", "s3cret-token")
    c, _ = client
    assert c.get("/healthz").status_code == 200
