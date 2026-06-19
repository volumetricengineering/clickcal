"""Application configuration loaded from environment variables / .env file."""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for the clickcal service.

    Values are read from environment variables (prefixed with ``CLICKCAL_``)
    or a local ``.env`` file.
    """

    model_config = SettingsConfigDict(
        env_prefix="CLICKCAL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ClickUp personal access token (e.g. "pk_12345_ABCDE...").
    token: str

    # The ClickUp space whose tasks should be exported.
    space_id: str

    # Comma-separated list IDs *or* list names to exclude from the feed.
    # Names are matched case-insensitively. Kept as a raw string so that
    # pydantic-settings does not try to JSON-decode it; use the parsed
    # ``excluded_lists`` property below.
    excluded_lists_raw: str = Field(
        default="",
        validation_alias=AliasChoices(
            "CLICKCAL_EXCLUDED_LISTS", "CLICKCAL_EXCLUDED_LISTS_RAW"
        ),
    )

    # Whether to include tasks whose status is "closed"/done.
    include_closed: bool = False

    # Whether to also include subtasks.
    include_subtasks: bool = True

    # Calendar name shown in clients subscribing to the feed.
    calendar_name: str = "ClickUp"

    # IANA timezone of the ClickUp workspace (e.g. "Europe/Berlin"). ClickUp
    # stores all-day dates as local midnight, so this is needed to recognize
    # them and to render timed events in the right zone. Defaults to UTC.
    timezone: str = "UTC"

    # How long (seconds) a rendered feed is reused before refetching from
    # ClickUp. Calendar clients poll frequently, so this avoids hammering the
    # API. Set to 0 to disable caching.
    cache_ttl: float = 300.0

    # Optional secret that makes the feed URL unguessable. When set, the feed is
    # served at /calendar/<token>.ics and any other token 404s. When unset (the
    # default), the feed stays at /calendar.ics with no protection. Use a long
    # random value (e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
    # and always serve over HTTPS, since the URL itself is the credential.
    feed_token: str = ""

    @property
    def excluded_lists(self) -> list[str]:
        """List IDs/names to exclude, parsed from the comma-separated value."""
        return [item.strip() for item in self.excluded_lists_raw.split(",") if item.strip()]


def get_settings() -> Settings:
    """Construct settings, raising a clear error if required vars are missing."""
    return Settings()  # type: ignore[call-arg]
