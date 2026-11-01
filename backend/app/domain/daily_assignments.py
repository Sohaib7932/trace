"""Pure local-calendar arithmetic, not assignment creation or quota enforcement."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from uuid import UUID

from app.domain.clock import as_utc

MAX_NEW_ASSIGNMENTS_PER_LOCAL_DAY = 3


@dataclass(frozen=True)
class LocalDayWindow:
    local_date: date
    utc_start: datetime
    utc_end: datetime

    def __post_init__(self) -> None:
        if type(self.local_date) is not date:
            raise ValueError("Local-day identity must be a calendar date")
        if self.utc_start.utcoffset() != timedelta(0) or self.utc_end.utcoffset() != timedelta(0):
            raise ValueError("Local-day boundaries must be explicit UTC timestamps")
        if self.utc_end <= self.utc_start:
            raise ValueError("Local-day window must have positive duration")


@dataclass(frozen=True)
class ResolvedLearnerTimezone:
    """Future server-owned resolver output. A label alone never resolves timezone rules."""

    learner_id: UUID
    timezone_key: str
    authority_revision: str
    resolved_timezone: tzinfo


def local_day_window(at: datetime, resolved_timezone: tzinfo) -> LocalDayWindow:
    """Use only an explicitly supplied rule set; never consult host timezone or zone files.

    Ambiguous/nonexistent midnight boundaries require a separately approved resolver
    decision. This helper fails closed rather than selecting a DST/travel policy.
    """
    try:
        if not isinstance(at, datetime) or not isinstance(resolved_timezone, tzinfo):
            raise ValueError("An aware instant and explicitly resolved timezone are required")
        instant = as_utc(at)
        local_date = instant.astimezone(resolved_timezone).date()
        boundaries = (
            datetime.combine(local_date, time.min, resolved_timezone),
            datetime.combine(local_date + timedelta(days=1), time.min, resolved_timezone),
        )
        converted = []
        for boundary in boundaries:
            if boundary.utcoffset() is None or (
                boundary.replace(fold=0).utcoffset() != boundary.replace(fold=1).utcoffset()
            ):
                raise ValueError("Explicit local-day boundary resolution is required")
            utc = boundary.astimezone(UTC)
            if utc.astimezone(resolved_timezone).replace(tzinfo=None) != boundary.replace(
                tzinfo=None
            ):
                raise ValueError("Explicit local-day boundary resolution is required")
            converted.append(utc)
        result = LocalDayWindow(local_date, converted[0], converted[1])
        if not result.utc_start <= instant < result.utc_end:
            raise ValueError("Resolved timezone does not establish a consistent local day")
        return result
    except (ValueError, TypeError, OverflowError):
        raise ValueError(
            "An aware instant and unambiguous resolved timezone are required"
        ) from None
