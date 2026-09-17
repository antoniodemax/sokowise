"""Natural-language periods resolve from the server clock in the business timezone."""

from datetime import UTC, date, datetime

import pytest
from app.ai.periods import AIPeriod, PeriodError, resolve_ai_period

TZ = "Africa/Nairobi"
# 2026-09-16 22:30 UTC is 01:30 on Thursday 17 September in Nairobi.
NOW = datetime(2026, 9, 16, 22, 30, tzinfo=UTC)


def _range(period: AIPeriod, **kw: date) -> tuple[date, date]:
    resolved = resolve_ai_period(TZ, period, kw.get("date_from"), kw.get("date_to"), now=NOW)
    return resolved.date_from, resolved.date_to


def test_named_periods_follow_the_business_local_calendar() -> None:
    assert _range(AIPeriod.TODAY) == (date(2026, 9, 17), date(2026, 9, 17))
    assert _range(AIPeriod.YESTERDAY) == (date(2026, 9, 16), date(2026, 9, 16))
    assert _range(AIPeriod.THIS_WEEK) == (date(2026, 9, 14), date(2026, 9, 17))  # Monday..today
    assert _range(AIPeriod.LAST_WEEK) == (date(2026, 9, 7), date(2026, 9, 13))  # Mon..Sun
    assert _range(AIPeriod.THIS_MONTH) == (date(2026, 9, 1), date(2026, 9, 17))
    assert _range(AIPeriod.LAST_MONTH) == (date(2026, 8, 1), date(2026, 8, 31))


def test_utc_and_nairobi_disagree_about_today_after_21_utc() -> None:
    assert resolve_ai_period("UTC", AIPeriod.TODAY, now=NOW).date_from == date(2026, 9, 16)
    assert resolve_ai_period(TZ, AIPeriod.TODAY, now=NOW).date_from == date(2026, 9, 17)


def test_year_and_month_boundaries() -> None:
    jan_first = datetime(2026, 12, 31, 21, 30, tzinfo=UTC)  # 00:30 on 1 January 2027 EAT
    last_month = resolve_ai_period(TZ, AIPeriod.LAST_MONTH, now=jan_first)
    assert (last_month.date_from, last_month.date_to) == (date(2026, 12, 1), date(2026, 12, 31))
    this_month = resolve_ai_period(TZ, AIPeriod.THIS_MONTH, now=jan_first)
    assert (this_month.date_from, this_month.date_to) == (date(2027, 1, 1), date(2027, 1, 1))
    last_week = resolve_ai_period(TZ, AIPeriod.LAST_WEEK, now=jan_first)  # Friday 1 Jan 2027
    assert (last_week.date_from, last_week.date_to) == (date(2026, 12, 21), date(2026, 12, 27))


def test_custom_periods_are_bounded_and_never_in_the_future() -> None:
    assert _range(AIPeriod.CUSTOM, date_from=date(2026, 9, 1), date_to=date(2026, 9, 10)) == (
        date(2026, 9, 1),
        date(2026, 9, 10),
    )
    # A range that runs past today is cut at today rather than reporting future days.
    assert _range(AIPeriod.CUSTOM, date_from=date(2026, 9, 10), date_to=date(2026, 12, 31)) == (
        date(2026, 9, 10),
        date(2026, 9, 17),
    )
    with pytest.raises(PeriodError, match="future"):
        _range(AIPeriod.CUSTOM, date_from=date(2026, 9, 18), date_to=date(2026, 9, 20))
    with pytest.raises(PeriodError, match="before"):
        _range(AIPeriod.CUSTOM, date_from=date(2026, 9, 10), date_to=date(2026, 9, 1))
    with pytest.raises(PeriodError, match="at most 366"):
        _range(AIPeriod.CUSTOM, date_from=date(2025, 1, 1), date_to=date(2026, 9, 1))
    with pytest.raises(PeriodError, match="both"):
        _range(AIPeriod.CUSTOM, date_from=date(2026, 9, 1))


def test_period_bounds_are_timezone_aware_utc_instants() -> None:
    period = resolve_ai_period(TZ, AIPeriod.TODAY, now=NOW)
    assert period.start == datetime(2026, 9, 16, 21, 0, tzinfo=UTC)
    assert period.end == datetime(2026, 9, 17, 21, 0, tzinfo=UTC)
