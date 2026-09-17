"""Helpers shared by the v1 routers (query-parameter periods for exports)."""

from datetime import date

from app.analytics.periods import Period, period_for_dates
from app.core.context import BusinessContext
from app.core.errors import AppError


class InvalidPeriodError(AppError):
    status_code = 422
    code = "INVALID_PERIOD"


def optional_period(
    ctx: BusinessContext, date_from: date | None, date_to: date | None
) -> Period | None:
    """`date_from`/`date_to` as local calendar days in the business timezone, or None."""
    if date_from is None and date_to is None:
        return None
    if date_from is None or date_to is None:
        raise InvalidPeriodError("date_from and date_to must be given together")
    try:
        return period_for_dates(ctx.timezone, date_from, date_to)
    except ValueError as exc:
        raise InvalidPeriodError(str(exc)) from None
