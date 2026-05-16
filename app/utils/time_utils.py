"""Timezone-safe timestamp utilities."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
MARKET_TIMEZONE = ZoneInfo("America/New_York")


def now_utc() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(tz=UTC)


def ensure_timezone(value: datetime, timezone: str | ZoneInfo = UTC) -> datetime:
    """Return a timezone-aware datetime, assigning timezone to naive values."""

    tz = _as_zoneinfo(timezone)
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def to_utc(value: datetime) -> datetime:
    """Convert a datetime to timezone-aware UTC."""

    return ensure_timezone(value, UTC).astimezone(UTC)


def to_market_time(value: datetime, timezone: str | ZoneInfo = MARKET_TIMEZONE) -> datetime:
    """Convert a datetime to the configured market timezone."""

    return ensure_timezone(value, UTC).astimezone(_as_zoneinfo(timezone))


def parse_datetime(value: str | date | datetime, timezone: str | ZoneInfo = MARKET_TIMEZONE) -> datetime:
    """Parse strings, dates, or datetimes into timezone-aware datetimes."""

    tz = _as_zoneinfo(timezone)
    if isinstance(value, datetime):
        return ensure_timezone(value, tz)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=tz)
    parsed = datetime.fromisoformat(value)
    return ensure_timezone(parsed, tz)


def validate_date_range(
    start: datetime,
    end: datetime,
    timezone: str | ZoneInfo = MARKET_TIMEZONE,
) -> tuple[datetime, datetime]:
    """Validate and normalize a start/end datetime range to UTC."""

    start_utc = ensure_timezone(start, timezone).astimezone(UTC)
    end_utc = ensure_timezone(end, timezone).astimezone(UTC)
    if start_utc >= end_utc:
        raise ValueError("start must be earlier than end.")
    return start_utc, end_utc


def _as_zoneinfo(timezone: str | ZoneInfo) -> ZoneInfo:
    if isinstance(timezone, ZoneInfo):
        return timezone
    return ZoneInfo(timezone)
