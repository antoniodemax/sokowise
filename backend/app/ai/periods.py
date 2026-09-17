"""Natural-language periods → validated business-local date ranges (PRD BR-10).

The model never supplies the current date: "today" is resolved here from the
server clock in the business timezone. Ranges are bounded and may not reach into
the future.
"""

from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.analytics.periods import Period, period_for_dates

MAX_DAYS = 366


class AIPeriod(StrEnum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    THIS_WEEK = "this_week"
    LAST_WEEK = "last_week"
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    CUSTOM = "custom"


class PeriodError(ValueError):
    """A reason the model can read and act on (asked back to the user or corrected)."""


def local_today(timezone: str, now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(ZoneInfo(timezone)).date()


def resolve_ai_period(
    timezone: str,
    period: AIPeriod,
    date_from: date | None = None,
    date_to: date | None = None,
    *,
    now: datetime | None = None,
) -> Period:
    today = local_today(timezone, now)
    match period:
        case AIPeriod.TODAY:
            start, end = today, today
        case AIPeriod.YESTERDAY:
            start = end = today - timedelta(days=1)
        case AIPeriod.THIS_WEEK:
            start, end = today - timedelta(days=today.weekday()), today
        case AIPeriod.LAST_WEEK:
            end = today - timedelta(days=today.weekday() + 1)  # last Sunday
            start = end - timedelta(days=6)
        case AIPeriod.THIS_MONTH:
            start, end = today.replace(day=1), today
        case AIPeriod.LAST_MONTH:
            end = today.replace(day=1) - timedelta(days=1)
            start = end.replace(day=1)
        case AIPeriod.CUSTOM:
            if date_from is None or date_to is None:
                raise PeriodError("A custom period needs both date_from and date_to (YYYY-MM-DD)")
            start, end = date_from, date_to
    if end < start:
        raise PeriodError("date_to must not be before date_from")
    if start > today:
        raise PeriodError(f"That period is in the future; today is {today.isoformat()}")
    if end > today:
        end = today  # a range that runs past today is cut at today, never into the future
    if (end - start).days >= MAX_DAYS:
        raise PeriodError(f"A period may span at most {MAX_DAYS} days")
    return period_for_dates(timezone, start, end)
