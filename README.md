# clickcal

Serve a ClickUp space's tasks as an iCal feed over HTTP, so you can subscribe
to your ClickUp tasks from any calendar app (Google Calendar, Apple Calendar,
Outlook, …).

Each task that has a **start date** and/or **due date** becomes a calendar
event. The event summary is the task name; the description includes the task's
description, list, status, and a link back to ClickUp.

By default **all tasks in the configured space** are included. You can opt out
of specific lists by id or name.

## Setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env
# edit .env: set CLICKCAL_TOKEN and CLICKCAL_SPACE_ID
```

Get a personal access token in ClickUp under **Settings → Apps → API Token**
(it looks like `pk_…`).

The **space id** is the number in a ClickUp URL after `/v/o/s/` (or visible via
the API). 

## Run

```bash
uv run clickcal
# or: uv run python -m clickcal
```

Then subscribe your calendar app to:

```
http://<host>:8000/calendar.ics
```

`GET /healthz` returns a basic health check.

## Making the feed private

The feed is unauthenticated by default. To keep it private, set a secret
`CLICKCAL_FEED_TOKEN`. The feed then moves to an unguessable URL and the plain
path returns `404`:

```bash
# generate a token
python -c "import secrets; print(secrets.token_urlsafe(32))"

# ...set it as CLICKCAL_FEED_TOKEN, then subscribe to:
https://<host>/calendar/<token>.ics
```

Notes:

- This works with every calendar client, because the secret lives in the URL.
- The URL **is** the credential — treat it like a password and always serve the
  feed over **HTTPS** (e.g. behind a reverse proxy) so it never travels in the
  clear. Rotate by changing the token (subscribers must re-subscribe).
- A wrong or missing token returns `404`, not `401`, so the feed's existence
  isn't revealed. `/healthz` stays open.

## Docker

```bash
docker build -t clickcal .
docker run -p 8000:8000 --env-file .env clickcal
```

The image runs as a non-root user and ships a `HEALTHCHECK` against `/healthz`.
Pass configuration via `--env-file .env` or individual `-e CLICKCAL_… ` flags;
the `.env` file itself is excluded from the image.

### Docker Compose

A `docker-compose.yml` is provided. It builds the image, loads config from
`.env`, and publishes the service:

```bash
cp .env.example .env   # fill in CLICKCAL_TOKEN, CLICKCAL_SPACE_ID, etc.
docker compose up -d --build
```

The service listens on port 8000 by default. Override the host port with
`CLICKCAL_HOST_PORT` (the in-container port stays 8000):

```bash
CLICKCAL_HOST_PORT=9000 docker compose up -d
```

`docker compose ps` shows health (from the image's `HEALTHCHECK`), and the
container restarts automatically unless explicitly stopped.

## Configuration

All settings are environment variables (or lines in `.env`), prefixed
`CLICKCAL_`:

| Variable                   | Required | Default     | Description                                                  |
| -------------------------- | -------- | ----------- | ------------------------------------------------------------ |
| `CLICKCAL_TOKEN`           | yes      | —           | ClickUp personal access token.                               |
| `CLICKCAL_SPACE_ID`        | yes      | —           | Space whose tasks to export.                                 |
| `CLICKCAL_EXCLUDED_LISTS`  | no       | (none)      | Comma-separated list ids or names to exclude (names case-insensitive). |
| `CLICKCAL_INCLUDE_CLOSED`  | no       | `false`     | Include closed/done tasks.                                   |
| `CLICKCAL_INCLUDE_SUBTASKS`| no       | `true`      | Include subtasks.                                            |
| `CLICKCAL_CALENDAR_NAME`   | no       | `ClickUp`   | Display name of the calendar.                                |
| `CLICKCAL_TIMEZONE`        | no       | `UTC`       | IANA timezone of the workspace (e.g. `Europe/Berlin`), used to render timed events. |
| `CLICKCAL_CACHE_TTL`       | no       | `300`       | Seconds to reuse a rendered feed before refetching from ClickUp (`0` disables caching). |
| `CLICKCAL_FEED_TOKEN`      | no       | (none)      | Secret to make the feed private: serves it at `/calendar/<token>.ics` and 404s the plain path. |
| `CLICKCAL_HOST`            | no       | `0.0.0.0`   | HTTP bind host.                                              |
| `CLICKCAL_PORT`            | no       | `8000`      | HTTP port.                                                   |

## Caching

The whole feed is rebuilt from ClickUp at most once per `CLICKCAL_CACHE_TTL`
seconds (default 5 minutes) and reused for all requests in between, so frequent
calendar-client polling doesn't hammer the ClickUp API. A burst of concurrent
requests triggers only a single rebuild, and if a refresh fails (e.g. ClickUp is
down) the last good feed is served rather than an error.

Responses carry `ETag` and `Cache-Control` headers, so clients and proxies that
support conditional requests get a `304 Not Modified` when the feed is unchanged.

## All-day vs. timed events

ClickUp's API does not report whether a task's dates are "all-day", so clickcal
infers it: a task is rendered as a **timed** event only when its start and due
fall on the **same day** with a real (sub-day) duration. Multi-day ranges,
single-point dates, and due-only deadlines become **all-day** events, so they
sit in the calendar's all-day banner instead of polluting your timed schedule.

## Tests

```bash
uv run pytest
```
