"""credit_transactions — the customer credit ledger, append-only (DATA_MAPPING §3.12).

Rows are added only through `services.credit.post_entry`, which also moves the
`customers.balance` cache under the customer row lock. Nothing here updates or
deletes a ledger row.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CreditTransaction, Customer

MAX_LIST_LIMIT = 500

DebtorSort = Literal["balance", "age"]


async def add_entry(session: AsyncSession, entry: CreditTransaction) -> CreditTransaction:
    session.add(entry)
    await session.flush()
    return entry


async def list_entries(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    customer_id: uuid.UUID,
    limit: int = MAX_LIST_LIMIT,
) -> list[CreditTransaction]:
    """Newest first by business time (`occurred_at`), then posting order.

    `balance_after` was computed in posting order; entries are not backdated in Phase 7,
    so the two orders coincide. Should a later phase backdate an entry, the running
    balance shown next to it still reflects when it was posted (same rule as
    `inventory_movements.quantity_after`, DATA_MAPPING §3.7).
    """
    result = await session.scalars(
        select(CreditTransaction)
        .where(
            CreditTransaction.business_id == business_id,
            CreditTransaction.customer_id == customer_id,
        )
        .order_by(
            CreditTransaction.occurred_at.desc(),
            CreditTransaction.created_at.desc(),
            CreditTransaction.id.desc(),
        )
        .limit(min(limit, MAX_LIST_LIMIT))
    )
    return list(result)


async def get_entry_by_idempotency_key(
    session: AsyncSession, *, business_id: uuid.UUID, idempotency_key: uuid.UUID
) -> CreditTransaction | None:
    result = await session.scalars(
        select(CreditTransaction).where(
            CreditTransaction.business_id == business_id,
            CreditTransaction.idempotency_key == idempotency_key,
        )
    )
    return result.one_or_none()


async def sum_entries(
    session: AsyncSession, *, business_id: uuid.UUID, customer_id: uuid.UUID
) -> Decimal:
    """Σ amount over the ledger — what `customers.balance` caches (PRD BR-7)."""
    total = await session.scalar(
        select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
            CreditTransaction.business_id == business_id,
            CreditTransaction.customer_id == customer_id,
        )
    )
    return Decimal(total or 0).quantize(Decimal("0.01"))


@dataclass(frozen=True, slots=True)
class DebtorRow:
    customer: Customer
    oldest_unpaid_charge_at: datetime | None


async def list_debtors(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    sort: DebtorSort = "balance",
    limit: int = MAX_LIST_LIMIT,
) -> list[DebtorRow]:
    """Customers with `balance > 0`, with the date of their oldest unpaid charge (FIFO).

    FIFO: every positive entry (CHARGE, ADJUSTMENT +) is paid off in `occurred_at` order
    by the total of negative entries; the oldest positive entry whose running total
    exceeds what has been paid is the oldest unpaid one. One aggregate query; no
    per-customer round trips.
    """
    ct = CreditTransaction
    running = (
        select(
            ct.customer_id.label("customer_id"),
            ct.occurred_at.label("occurred_at"),
            func.sum(ct.amount)
            .over(partition_by=ct.customer_id, order_by=(ct.occurred_at, ct.created_at, ct.id))
            .label("charged_so_far"),
        )
        .where(ct.business_id == business_id, ct.amount > 0)
        .subquery("running")
    )
    paid = (
        select(ct.customer_id.label("customer_id"), (-func.sum(ct.amount)).label("paid"))
        .where(ct.business_id == business_id, ct.amount < 0)
        .group_by(ct.customer_id)
        .subquery("paid")
    )
    oldest_unpaid = (
        select(
            running.c.customer_id.label("customer_id"),
            func.min(running.c.occurred_at).label("oldest_unpaid_charge_at"),
        )
        .select_from(running)
        .outerjoin(paid, paid.c.customer_id == running.c.customer_id)
        .where(running.c.charged_so_far > func.coalesce(paid.c.paid, 0))
        .group_by(running.c.customer_id)
        .subquery("oldest_unpaid")
    )
    stmt = (
        select(Customer, oldest_unpaid.c.oldest_unpaid_charge_at)
        .outerjoin(oldest_unpaid, oldest_unpaid.c.customer_id == Customer.id)
        .where(Customer.business_id == business_id, Customer.balance > 0)
    )
    if sort == "age":
        stmt = stmt.order_by(
            oldest_unpaid.c.oldest_unpaid_charge_at.asc().nulls_last(),
            Customer.balance.desc(),
            func.lower(Customer.name),
            Customer.id,
        )
    else:
        stmt = stmt.order_by(Customer.balance.desc(), func.lower(Customer.name), Customer.id)
    rows = await session.execute(stmt.limit(min(limit, MAX_LIST_LIMIT)))
    return [DebtorRow(customer=customer, oldest_unpaid_charge_at=at) for customer, at in rows]
