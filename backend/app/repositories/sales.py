"""sales, sale_items, payments (docs/DATA_MAPPING.md §3.9-§3.11). Scoped by `business_id`.

`items` and `payments` are loaded eagerly wherever a sale is returned (relationships
are `lazy="raise"`).
"""

import uuid
from datetime import datetime

from sqlalchemy import Select, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Sale

MAX_LIST_LIMIT = 200


def _with_children(stmt: Select[tuple[Sale]]) -> Select[tuple[Sale]]:
    return stmt.options(selectinload(Sale.items), selectinload(Sale.payments))


async def get_sale(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    sale_id: uuid.UUID,
    created_by: uuid.UUID | None = None,
    sold_from: datetime | None = None,
    for_update: bool = False,
) -> Sale | None:
    """One sale. `created_by`/`sold_from` narrow the view for STAFF (own sales, today)."""
    stmt = select(Sale).where(Sale.business_id == business_id, Sale.id == sale_id)
    if created_by is not None:
        stmt = stmt.where(Sale.created_by == created_by)
    if sold_from is not None:
        stmt = stmt.where(Sale.sold_at >= sold_from)
    if for_update:
        stmt = stmt.with_for_update(of=Sale)
    result = await session.scalars(_with_children(stmt))
    return result.one_or_none()


async def get_sale_by_idempotency_key(
    session: AsyncSession, *, business_id: uuid.UUID, idempotency_key: uuid.UUID
) -> Sale | None:
    result = await session.scalars(
        _with_children(
            select(Sale).where(
                Sale.business_id == business_id, Sale.idempotency_key == idempotency_key
            )
        )
    )
    return result.one_or_none()


async def list_sales(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    sold_from: datetime | None = None,
    sold_until: datetime | None = None,
    customer_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    limit: int = MAX_LIST_LIMIT,
) -> list[Sale]:
    """Newest first. Voided sales are included (they carry their status)."""
    stmt = select(Sale).where(Sale.business_id == business_id)
    if sold_from is not None:
        stmt = stmt.where(Sale.sold_at >= sold_from)
    if sold_until is not None:
        stmt = stmt.where(Sale.sold_at < sold_until)
    if customer_id is not None:
        stmt = stmt.where(Sale.customer_id == customer_id)
    if created_by is not None:
        stmt = stmt.where(Sale.created_by == created_by)
    stmt = stmt.order_by(Sale.sold_at.desc(), Sale.id.desc()).limit(min(limit, MAX_LIST_LIMIT))
    return list(await session.scalars(_with_children(stmt)))


EXPORT_BATCH = 200


async def export_batch(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    sold_from: datetime | None,
    sold_until: datetime | None,
    after: tuple[datetime, uuid.UUID] | None,
    batch: int = EXPORT_BATCH,
) -> list[Sale]:
    """One keyset page of sales with their lines and tenders, oldest first (CSV export)."""
    stmt = select(Sale).where(Sale.business_id == business_id)
    if sold_from is not None:
        stmt = stmt.where(Sale.sold_at >= sold_from)
    if sold_until is not None:
        stmt = stmt.where(Sale.sold_at < sold_until)
    if after is not None:
        stmt = stmt.where(tuple_(Sale.sold_at, Sale.id) > after)
    stmt = stmt.order_by(Sale.sold_at.asc(), Sale.id.asc()).limit(batch)
    return list(await session.scalars(_with_children(stmt)))
