"""Analytics (ROADMAP analytics phase; PRD FR-I, BR-10, BR-15, BR-16). OWNER-only (§16).

Periods: `period=today|yesterday|this_week|this_month` or `period=custom` with
`date_from` and `date_to` (inclusive local calendar days in the business timezone).
"""

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import queries
from app.analytics.periods import Granularity, NamedPeriod, Period, resolve_period
from app.api.deps import require_owner
from app.core.context import BusinessContext
from app.core.errors import AppError
from app.db.session import get_session
from app.schemas.analytics import (
    BucketOut,
    CategoryPerformanceOut,
    PeriodOut,
    ProductPerformanceOut,
    SlowProductOut,
    SummaryOut,
    TimeseriesOut,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

OwnerCtx = Annotated[BusinessContext, Depends(require_owner)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
MAX_CUSTOM_DAYS = 366


class InvalidPeriodError(AppError):
    status_code = 422
    code = "INVALID_PERIOD"


def _period(
    ctx: BusinessContext, period: NamedPeriod, date_from: date | None, date_to: date | None
) -> Period:
    try:
        resolved = resolve_period(ctx.timezone, period, date_from, date_to)
    except ValueError as exc:
        raise InvalidPeriodError(str(exc)) from None
    if (resolved.date_to - resolved.date_from).days >= MAX_CUSTOM_DAYS:
        raise InvalidPeriodError(f"A period may span at most {MAX_CUSTOM_DAYS} days")
    return resolved


def _period_out(period: Period) -> PeriodOut:
    return PeriodOut(timezone=period.timezone, date_from=period.date_from, date_to=period.date_to)


PeriodQuery = Annotated[NamedPeriod, Query()]


@router.get("/summary", response_model=SummaryOut)
async def summary(
    ctx: OwnerCtx,
    session: SessionDep,
    period: PeriodQuery = NamedPeriod.TODAY,
    date_from: date | None = None,
    date_to: date | None = None,
) -> SummaryOut:
    resolved = _period(ctx, period, date_from, date_to)
    result = await queries.summary(session, ctx.business_id, resolved)
    return SummaryOut(period=_period_out(resolved), **asdict(result))


@router.get("/timeseries", response_model=TimeseriesOut)
async def timeseries(
    ctx: OwnerCtx,
    session: SessionDep,
    granularity: Granularity = Granularity.DAY,
    period: PeriodQuery = NamedPeriod.THIS_MONTH,
    date_from: date | None = None,
    date_to: date | None = None,
) -> TimeseriesOut:
    resolved = _period(ctx, period, date_from, date_to)
    buckets = await queries.timeseries(session, ctx.business_id, resolved, granularity)
    return TimeseriesOut(
        period=_period_out(resolved),
        granularity=granularity.value,
        buckets=[BucketOut(**asdict(b)) for b in buckets],
    )


@router.get("/products", response_model=list[ProductPerformanceOut])
async def products(
    ctx: OwnerCtx,
    session: SessionDep,
    period: PeriodQuery = NamedPeriod.THIS_MONTH,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: queries.ProductSort = "revenue",
    limit: Annotated[int, Query(ge=1, le=queries.MAX_ROWS)] = 20,
) -> list[ProductPerformanceOut]:
    resolved = _period(ctx, period, date_from, date_to)
    rows = await queries.product_performance(
        session, ctx.business_id, resolved, sort=sort, limit=limit
    )
    return [ProductPerformanceOut(**asdict(row)) for row in rows]


@router.get("/slow-products", response_model=list[SlowProductOut])
async def slow_products(
    ctx: OwnerCtx,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=365, description="no sale in this many days")] = 30,
    limit: Annotated[int, Query(ge=1, le=queries.MAX_ROWS)] = 20,
) -> list[SlowProductOut]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = await queries.slow_products(session, ctx.business_id, since=since, limit=limit)
    return [SlowProductOut(**asdict(row)) for row in rows]


@router.get("/categories", response_model=list[CategoryPerformanceOut])
async def categories(
    ctx: OwnerCtx,
    session: SessionDep,
    period: PeriodQuery = NamedPeriod.THIS_MONTH,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[CategoryPerformanceOut]:
    resolved = _period(ctx, period, date_from, date_to)
    rows = await queries.category_performance(session, ctx.business_id, resolved)
    return [CategoryPerformanceOut(**asdict(row)) for row in rows]
