"""Expenses: record, edit, soft-delete, list, export (PRD FR-H, BR-6; DATA_MAPPING §3.13).

An expense is money the business spent — never a restock (that is stock in,
BR-6) and never anything that touches sales, stock or customer balances. It sits
below gross profit in the figures: `net_profit = gross_profit - expenses` (FR-I1).

OWNER-only throughout (PRD §16 "Record expenses"). Edits and deletes are audited
(FR-H3) inside the same transaction; deletion is a soft delete (`deleted_at`) so
history stays and totals simply skip the row.

No idempotency key: the PRD requires one for sales only (FR-F6); an accidental
duplicate expense is visible in the list and deletable, so the extra machinery is
not worth its surface here.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import Period
from app.core.context import BusinessContext, ClientInfo
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.session import transaction
from app.models import Expense
from app.models.enums import MoneyReceivedMethod
from app.repositories import expenses as expense_repo
from app.schemas.expenses import SUGGESTED_CATEGORIES, ExpenseCreateRequest, ExpenseUpdateRequest
from app.services import audit
from app.services.audit import AuditAction

ENTITY_TYPE = "expense"
CENT = Decimal("0.01")
_FUTURE_TOLERANCE = timedelta(minutes=5)


class ExpenseDeletedError(ConflictError):
    code = "EXPENSE_DELETED"


class ExpenseValidationError(AppError):
    status_code = 422


def _resolve_incurred_at(requested: datetime | None) -> datetime:
    now = datetime.now(UTC)
    if requested is None:
        return now
    if requested > now + _FUTURE_TOLERANCE:
        raise ExpenseValidationError(
            "incurred_at cannot be in the future", code="EXPENSE_IN_FUTURE"
        )
    return min(requested, now)


async def _get(
    session: AsyncSession, ctx: BusinessContext, expense_id: uuid.UUID, *, for_update: bool = False
) -> Expense:
    expense = await expense_repo.get_expense(
        session, business_id=ctx.business_id, expense_id=expense_id, for_update=for_update
    )
    if expense is None:
        raise NotFoundError("Expense not found")
    return expense


async def create_expense(
    session: AsyncSession, ctx: BusinessContext, data: ExpenseCreateRequest, client: ClientInfo
) -> Expense:
    expense = Expense(
        business_id=ctx.business_id,
        amount=data.amount.quantize(CENT),
        category=data.category,
        payment_method=data.payment_method,
        reference=data.reference,
        note=data.note,
        incurred_at=_resolve_incurred_at(data.incurred_at),
        created_by=ctx.user_id,
    )
    async with transaction(session):
        await expense_repo.add_expense(session, expense)
        await session.refresh(expense)
    return expense


async def get_expense(
    session: AsyncSession, ctx: BusinessContext, expense_id: uuid.UUID
) -> Expense:
    return await _get(session, ctx, expense_id)


async def list_expenses(
    session: AsyncSession,
    ctx: BusinessContext,
    *,
    period: Period | None,
    category: str | None,
    payment_method: MoneyReceivedMethod | None,
    include_deleted: bool,
    limit: int,
) -> list[Expense]:
    return await expense_repo.list_expenses(
        session,
        ctx.business_id,
        incurred_from=period.start if period else None,
        incurred_until=period.end if period else None,
        category=category,
        payment_method=payment_method,
        include_deleted=include_deleted,
        limit=limit,
    )


async def update_expense(
    session: AsyncSession,
    ctx: BusinessContext,
    expense_id: uuid.UUID,
    data: ExpenseUpdateRequest,
    client: ClientInfo,
) -> Expense:
    """Change the fields present; audit the ones that actually changed (FR-H3)."""
    async with transaction(session):
        expense = await _get(session, ctx, expense_id, for_update=True)
        if expense.deleted_at is not None:
            raise ExpenseDeletedError("This expense was deleted")
        before: dict[str, object] = {}
        after: dict[str, object] = {}
        for name in data.model_fields_set:
            value = getattr(data, name)
            if name == "amount" and value is not None:
                value = value.quantize(CENT)
            if name == "incurred_at" and value is not None:
                value = _resolve_incurred_at(value)
            current = getattr(expense, name)
            if current == value:
                continue
            before[name] = _plain(current)
            after[name] = _plain(value)
            setattr(expense, name, value)
        if after:
            await session.flush()
            await audit.record(
                session,
                ctx,
                action=AuditAction.EXPENSE_UPDATE,
                entity_type=ENTITY_TYPE,
                entity_id=expense.id,
                before=before,
                after=after,
                client=client,
            )
        await session.refresh(expense)
    return expense


async def delete_expense(
    session: AsyncSession, ctx: BusinessContext, expense_id: uuid.UUID, client: ClientInfo
) -> None:
    """Soft delete: the row stays, totals and listings skip it. Idempotent."""
    async with transaction(session):
        expense = await _get(session, ctx, expense_id, for_update=True)
        if expense.deleted_at is not None:
            return
        expense.deleted_at = datetime.now(UTC)
        await session.flush()
        await audit.record(
            session,
            ctx,
            action=AuditAction.EXPENSE_DELETE,
            entity_type=ENTITY_TYPE,
            entity_id=expense.id,
            before={
                "amount": str(expense.amount),
                "category": expense.category,
                "deleted_at": None,
            },
            after={"deleted_at": expense.deleted_at.isoformat()},
            client=client,
        )


async def suggested_categories(session: AsyncSession, ctx: BusinessContext) -> list[str]:
    used = await expense_repo.used_categories(session, ctx.business_id)
    return list(SUGGESTED_CATEGORIES) + sorted(set(used) - set(SUGGESTED_CATEGORIES))


async def iter_export(
    session: AsyncSession,
    ctx: BusinessContext,
    *,
    period: Period | None,
    category: str | None,
    payment_method: MoneyReceivedMethod | None,
) -> AsyncIterator[Expense]:
    """Oldest first, in keyset batches, so a large export never sits in memory at once."""
    after: tuple[datetime, uuid.UUID] | None = None
    while True:
        batch = await expense_repo.export_batch(
            session,
            ctx.business_id,
            incurred_from=period.start if period else None,
            incurred_until=period.end if period else None,
            category=category,
            payment_method=payment_method,
            after=after,
        )
        for expense in batch:
            yield expense
        if len(batch) < expense_repo.EXPORT_BATCH:
            return
        after = (batch[-1].incurred_at, batch[-1].id)


def _plain(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, MoneyReceivedMethod):
        return value.value
    return value
