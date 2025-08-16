from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def now_utc() -> datetime:
    """Returns the current time in UTC."""
    return datetime.now(timezone.utc)

def now_msk(app_tz: ZoneInfo) -> datetime:
    """Returns the current time in the application's timezone (Moscow)."""
    return datetime.now(app_tz)

def to_utc(dt: datetime, tz: ZoneInfo) -> datetime:
    """Converts a datetime object to UTC, assuming it's in the given timezone if naive."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)

def utc_to_local(dt_utc: datetime, tz: ZoneInfo) -> datetime:
    """Converts a UTC datetime object to the local application timezone."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(tz)
