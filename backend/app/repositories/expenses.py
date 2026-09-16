"""expenses (docs/DATA_MAPPING.md §3.13). Every query is scoped by `business_id`.

Soft-deleted rows (`deleted_at` set) stay for history; listings and totals skip
them unless asked.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Expense
from app.models.enums import MoneyReceivedMethod

MAX_LIST_LIMIT = 200
EXPORT_BATCH = 500


async def add_expense(session: AsyncSession, expense: Expense) -> Expense:
    session.add(expense)
    await session.flush()
    return expense


async def get_expense(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    expense_id: uuid.UUID,
    for_update: bool = False,
) -> Expense | None:
    stmt = select(Expense).where(Expense.business_id == business_id, Expense.id == expense_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).one_or_none()


async def list_expenses(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    incurred_from: datetime | None = None,
    incurred_until: datetime | None = None,
    category: str | None = None,
    payment_method: MoneyReceivedMethod | None = None,
    include_deleted: bool = False,
    limit: int = MAX_LIST_LIMIT,
) -> list[Expense]:
    """Newest first (`incurred_at`, then id)."""
    stmt = _filtered(
        business_id,
        incurred_from=incurred_from,
        incurred_until=incurred_until,
        category=category,
        payment_method=payment_method,
        include_deleted=include_deleted,
    )
    stmt = stmt.order_by(Expense.incurred_at.desc(), Expense.id.desc()).limit(
        min(limit, MAX_LIST_LIMIT)
    )
    return list(await session.scalars(stmt))


async def export_batch(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    incurred_from: datetime | None,
    incurred_until: datetime | None,
    category: str | None,
    payment_method: MoneyReceivedMethod | None,
    after: tuple[datetime, uuid.UUID] | None,
    batch: int = EXPORT_BATCH,
) -> list[Expense]:
    """One keyset page, oldest first, for streaming exports (never the whole table at once)."""
    stmt = _filtered(
        business_id,
        incurred_from=incurred_from,
        incurred_until=incurred_until,
        category=category,
        payment_method=payment_method,
        include_deleted=False,
    )
    if after is not None:
        stmt = stmt.where(tuple_(Expense.incurred_at, Expense.id) > after)
    stmt = stmt.order_by(Expense.incurred_at.asc(), Expense.id.asc()).limit(batch)
    return list(await session.scalars(stmt))


async def used_categories(session: AsyncSession, business_id: uuid.UUID) -> list[str]:
    result = await session.scalars(
        select(Expense.category)
        .where(Expense.business_id == business_id, Expense.deleted_at.is_(None))
        .distinct()
        .order_by(Expense.category)
    )
    return list(result)


async def totals_by_category(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    incurred_from: datetime,
    incurred_until: datetime,
) -> list[tuple[str, Decimal, int]]:
    rows = await session.execute(
        select(Expense.category, func.sum(Expense.amount), func.count(Expense.id))
        .where(
            Expense.business_id == business_id,
            Expense.deleted_at.is_(None),
            Expense.incurred_at >= incurred_from,
            Expense.incurred_at < incurred_until,
        )
        .group_by(Expense.category)
        .order_by(func.sum(Expense.amount).desc(), Expense.category)
    )
    return [(category, Decimal(total), int(count)) for category, total, count in rows]


async def totals_by_method(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    incurred_from: datetime,
    incurred_until: datetime,
) -> list[tuple[MoneyReceivedMethod, Decimal, int]]:
    rows = await session.execute(
        select(Expense.payment_method, func.sum(Expense.amount), func.count(Expense.id))
        .where(
            Expense.business_id == business_id,
            Expense.deleted_at.is_(None),
            Expense.incurred_at >= incurred_from,
            Expense.incurred_at < incurred_until,
        )
        .group_by(Expense.payment_method)
    )
    return [(method, Decimal(total), int(count)) for method, total, count in rows]


def _filtered(
    business_id: uuid.UUID,
    *,
    incurred_from: datetime | None,
    incurred_until: datetime | None,
    category: str | None,
    payment_method: MoneyReceivedMethod | None,
    include_deleted: bool,
) -> Select[tuple[Expense]]:
    stmt = select(Expense).where(Expense.business_id == business_id)
    if not include_deleted:
        stmt = stmt.where(Expense.deleted_at.is_(None))
    if incurred_from is not None:
        stmt = stmt.where(Expense.incurred_at >= incurred_from)
    if incurred_until is not None:
        stmt = stmt.where(Expense.incurred_at < incurred_until)
    if category is not None:
        stmt = stmt.where(Expense.category == category)
    if payment_method is not None:
        stmt = stmt.where(Expense.payment_method == payment_method)
    return stmt
