"""Platform-wide figures for the operator dashboard (docs/ARCHITECTURE.md §5.4).

This is the one deliberate exception to the rule that every query is scoped by
`business_id`: it aggregates across every tenant so the operator can see how the pilot is
going. It is reachable only through `require_platform_admin`, it is read-only, and it
returns counts and totals, never rows of tenant data — no phones, no owner names, no money
per business. Keep it that way; per-business detail belongs in that business's own screens.

Money is `Decimal`, never float. "Days" are local calendar days in `timezone`.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Date, Select, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AIMessage,
    Business,
    BusinessMembership,
    Customer,
    Expense,
    MpesaMessage,
    Product,
    Receipt,
    Sale,
    User,
)
from app.models.enums import AIMessageRole, MembershipRole, ProposalStatus, SaleStatus
from app.services.money import round_money

DEFAULT_TIMEZONE = "Africa/Nairobi"
SIGNUP_DAYS = 30
ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class Totals:
    businesses: int
    businesses_active: int
    users: int
    owners: int
    staff: int
    products: int
    customers: int
    sales: int
    revenue: Decimal
    expenses: int
    credit_outstanding: Decimal
    mpesa_messages: int
    receipts: int
    copilot_messages: int
    proposals_applied: int


@dataclass(frozen=True, slots=True)
class Recent:
    """Activity in the last `days` days."""

    days: int
    new_businesses: int
    sales: int
    revenue: Decimal
    businesses_with_sales: int
    users_signed_in: int


@dataclass(frozen=True, slots=True)
class SignupBucket:
    day: date
    businesses: int


@dataclass(frozen=True, slots=True)
class BusinessRow:
    id: uuid.UUID
    name: str
    business_type: str
    is_active: bool
    created_at: datetime
    products: int
    sales: int
    last_sale_at: datetime | None
    last_login_at: datetime | None


@dataclass(frozen=True, slots=True)
class PlatformOverview:
    generated_at: datetime
    timezone: str
    totals: Totals
    last_7_days: Recent
    last_30_days: Recent
    signups_by_day: list[SignupBucket]
    businesses: list[BusinessRow]


def _money(value: object) -> Decimal:
    return round_money(Decimal(str(value))) if value is not None else ZERO


async def _count(session: AsyncSession, statement: Select[tuple[int]]) -> int:
    return int(await session.scalar(statement) or 0)


async def _totals(session: AsyncSession) -> Totals:
    role_rows = (
        await session.execute(
            select(BusinessMembership.role, func.count(BusinessMembership.id)).group_by(
                BusinessMembership.role
            )
        )
    ).all()
    by_role = {role: int(count) for role, count in role_rows}
    sales_row = (
        await session.execute(
            select(func.count(Sale.id), func.sum(Sale.total_amount)).where(
                Sale.status == SaleStatus.COMPLETED
            )
        )
    ).one()
    return Totals(
        businesses=await _count(session, select(func.count(Business.id))),
        businesses_active=await _count(
            session, select(func.count(Business.id)).where(Business.is_active.is_(True))
        ),
        users=await _count(session, select(func.count(User.id))),
        owners=by_role.get(MembershipRole.OWNER, 0),
        staff=by_role.get(MembershipRole.STAFF, 0),
        products=await _count(session, select(func.count(Product.id))),
        customers=await _count(session, select(func.count(Customer.id))),
        sales=int(sales_row[0] or 0),
        revenue=_money(sales_row[1]),
        expenses=await _count(
            session, select(func.count(Expense.id)).where(Expense.deleted_at.is_(None))
        ),
        credit_outstanding=_money(
            await session.scalar(select(func.sum(Customer.balance)).where(Customer.balance > 0))
        ),
        mpesa_messages=await _count(session, select(func.count(MpesaMessage.id))),
        receipts=await _count(session, select(func.count(Receipt.id))),
        copilot_messages=await _count(
            session,
            select(func.count(AIMessage.id)).where(AIMessage.role == AIMessageRole.USER),
        ),
        proposals_applied=await _count(
            session,
            select(func.count(AIMessage.id)).where(
                AIMessage.proposal_status == ProposalStatus.APPLIED
            ),
        ),
    )


async def _recent(session: AsyncSession, *, now: datetime, days: int) -> Recent:
    since = now - timedelta(days=days)
    sales_row = (
        await session.execute(
            select(
                func.count(Sale.id),
                func.sum(Sale.total_amount),
                func.count(func.distinct(Sale.business_id)),
            ).where(Sale.status == SaleStatus.COMPLETED, Sale.sold_at >= since)
        )
    ).one()
    return Recent(
        days=days,
        new_businesses=await _count(
            session, select(func.count(Business.id)).where(Business.created_at >= since)
        ),
        sales=int(sales_row[0] or 0),
        revenue=_money(sales_row[1]),
        businesses_with_sales=int(sales_row[2] or 0),
        users_signed_in=await _count(
            session, select(func.count(User.id)).where(User.last_login_at >= since)
        ),
    )


async def _signups_by_day(
    session: AsyncSession, *, now: datetime, timezone: str
) -> list[SignupBucket]:
    today = now.astimezone(ZoneInfo(timezone)).date()
    first_day = today - timedelta(days=SIGNUP_DAYS - 1)
    local_day = cast(func.date_trunc("day", func.timezone(timezone, Business.created_at)), Date)
    rows = (
        await session.execute(
            select(local_day, func.count(Business.id))
            .where(Business.created_at >= now - timedelta(days=SIGNUP_DAYS + 1))
            .group_by(local_day)
        )
    ).all()
    counts = {day: int(count) for day, count in rows}
    days = [first_day + timedelta(days=i) for i in range(SIGNUP_DAYS)]
    return [SignupBucket(day=day, businesses=counts.get(day, 0)) for day in days]


async def _businesses(session: AsyncSession) -> list[BusinessRow]:
    products = (
        select(Product.business_id, func.count(Product.id).label("products"))
        .group_by(Product.business_id)
        .subquery()
    )
    sales = (
        select(
            Sale.business_id,
            func.count(Sale.id).label("sales"),
            func.max(Sale.sold_at).label("last_sale_at"),
        )
        .where(Sale.status == SaleStatus.COMPLETED)
        .group_by(Sale.business_id)
        .subquery()
    )
    logins = (
        select(
            BusinessMembership.business_id,
            func.max(User.last_login_at).label("last_login_at"),
        )
        .join(User, User.id == BusinessMembership.user_id)
        .group_by(BusinessMembership.business_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Business.id,
                Business.name,
                Business.business_type,
                Business.is_active,
                Business.created_at,
                func.coalesce(products.c.products, 0),
                func.coalesce(sales.c.sales, 0),
                sales.c.last_sale_at,
                logins.c.last_login_at,
            )
            .outerjoin(products, products.c.business_id == Business.id)
            .outerjoin(sales, sales.c.business_id == Business.id)
            .outerjoin(logins, logins.c.business_id == Business.id)
            .order_by(Business.created_at.desc())
        )
    ).all()
    return [
        BusinessRow(
            id=row[0],
            name=row[1],
            business_type=str(row[2]),
            is_active=bool(row[3]),
            created_at=row[4],
            products=int(row[5]),
            sales=int(row[6]),
            last_sale_at=row[7],
            last_login_at=row[8],
        )
        for row in rows
    ]


async def overview(
    session: AsyncSession, *, timezone: str = DEFAULT_TIMEZONE, now: datetime | None = None
) -> PlatformOverview:
    now = now or datetime.now(UTC)
    return PlatformOverview(
        generated_at=now,
        timezone=timezone,
        totals=await _totals(session),
        last_7_days=await _recent(session, now=now, days=7),
        last_30_days=await _recent(session, now=now, days=30),
        signups_by_day=await _signups_by_day(session, now=now, timezone=timezone),
        businesses=await _businesses(session),
    )


__all__ = [
    "DEFAULT_TIMEZONE",
    "SIGNUP_DAYS",
    "BusinessRow",
    "PlatformOverview",
    "Recent",
    "SignupBucket",
    "Totals",
    "overview",
]
