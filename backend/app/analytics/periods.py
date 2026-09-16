"""Period boundaries in the business timezone (PRD BR-10, FR-I1).

A period is a half-open UTC interval `[start, end)` derived from local dates:
`date_from` starts at local midnight, `date_to` ends at the *next* local midnight,
so both bounds are inclusive calendar days for the business. Named periods are
relative to "now" in the business timezone: `today`, `yesterday`, `this_week`
(Monday to today), `this_month` (the 1st to today).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo


class NamedPeriod(StrEnum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    THIS_WEEK = "this_week"
    THIS_MONTH = "this_month"
    CUSTOM = "custom"


class Granularity(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


@dataclass(frozen=True, slots=True)
class Period:
    timezone: str
    date_from: date  # inclusive, local
    date_to: date  # inclusive, local
    start: datetime  # UTC, inclusive
    end: datetime  # UTC, exclusive


def local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


def period_for_dates(timezone: str, date_from: date, date_to: date) -> Period:
    if date_to < date_from:
        msg = "date_to must not be before date_from"
        raise ValueError(msg)
    tz = ZoneInfo(timezone)
    return Period(
        timezone=timezone,
        date_from=date_from,
        date_to=date_to,
        start=local_midnight(date_from, tz),
        end=local_midnight(date_to + timedelta(days=1), tz),
    )


def resolve_period(
    timezone: str,
    named: NamedPeriod,
    date_from: date | None = None,
    date_to: date | None = None,
    *,
    now: datetime | None = None,
) -> Period:
    today = (now or datetime.now(UTC)).astimezone(ZoneInfo(timezone)).date()
    match named:
        case NamedPeriod.TODAY:
            return period_for_dates(timezone, today, today)
        case NamedPeriod.YESTERDAY:
            yesterday = today - timedelta(days=1)
            return period_for_dates(timezone, yesterday, yesterday)
        case NamedPeriod.THIS_WEEK:
            return period_for_dates(timezone, today - timedelta(days=today.weekday()), today)
        case NamedPeriod.THIS_MONTH:
            return period_for_dates(timezone, today.replace(day=1), today)
        case NamedPeriod.CUSTOM:
            if date_from is None or date_to is None:
                msg = "date_from and date_to are required for a custom period"
                raise ValueError(msg)
            return period_for_dates(timezone, date_from, date_to)
