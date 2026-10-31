from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware server timestamp is required")
    return value.astimezone(UTC)
