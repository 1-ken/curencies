"""Africa/Nairobi timezone helpers for API output and logging."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Union
from zoneinfo import ZoneInfo

KENYA_TZ = ZoneInfo("Africa/Nairobi")
KENYA_TIMEZONE_NAME = "Africa/Nairobi"


def now_kenya() -> datetime:
    """Current wall-clock time in Kenya."""
    return datetime.now(KENYA_TZ)


def now_kenya_iso() -> str:
    """ISO-8601 timestamp with Kenya offset for API responses."""
    return now_kenya().isoformat()


def parse_to_aware_utc(value: Union[str, datetime, None]) -> Optional[datetime]:
    """Parse ISO input into an aware UTC datetime."""
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    normalized = str(value).strip()
    if not normalized:
        return None

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except (TypeError, ValueError):
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_kenya(value: Union[str, datetime, None]) -> Optional[datetime]:
    """Convert a datetime or ISO string to Africa/Nairobi."""
    parsed = parse_to_aware_utc(value)
    if parsed is None:
        return None
    return parsed.astimezone(KENYA_TZ)


def format_kenya_iso(value: Union[str, datetime, None]) -> Optional[str]:
    """Serialize a datetime as ISO-8601 in Africa/Nairobi."""
    kenya = to_kenya(value)
    if kenya is None:
        return None
    return kenya.isoformat()


def format_kenya_display(value: Union[str, datetime, None]) -> str:
    """Human-readable Kenya local timestamp."""
    kenya = to_kenya(value)
    if kenya is None:
        return "—"
    return kenya.strftime("%Y-%m-%d %H:%M:%S %Z")


def kenya_logging_time(*args: object) -> tuple[int, ...]:
    """Struct time for logging.Formatter.converter (Africa/Nairobi).

    Accepts either ``secs`` (class-level) or ``(formatter, secs)`` when bound
    on a Formatter instance — same pattern as ``time.localtime``.
    """
    if not args:
        return now_kenya().timetuple()
    return datetime.fromtimestamp(float(args[-1]), tz=KENYA_TZ).timetuple()


def coerce_response_timestamp(value: Any) -> Any:
    """Convert datetime values in API payloads to Kenya ISO strings."""
    if isinstance(value, datetime):
        return format_kenya_iso(value)
    if isinstance(value, str):
        formatted = format_kenya_iso(value)
        return formatted if formatted is not None else value
    return value
