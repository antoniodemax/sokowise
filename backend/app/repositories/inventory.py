"""inventory_movements — append-only (docs/DATA_MAPPING.md §3.7). Scoped by `business_id`.

Rows are only ever added, through `services.inventory`, which also maintains the
`products.stock_quantity` cache in the same transaction.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InventoryMovement, Product
from app.models.enums import MovementType


async def add_movement(session: AsyncSession, movement: InventoryMovement) -> InventoryMovement:
    session.add(movement)
    await session.flush()
    return movement


async def list_movements_for_product(
    session: AsyncSession, *, business_id: uuid.UUID, product_id: uuid.UUID
) -> list[InventoryMovement]:
    """Commit order (`created_at`, then id), which is the order `quantity_after` follows."""
    result = await session.scalars(
        select(InventoryMovement)
        .where(
            InventoryMovement.business_id == business_id,
            InventoryMovement.product_id == product_id,
        )
        .order_by(InventoryMovement.created_at, InventoryMovement.id)
    )
    return list(result)


async def list_movements_for_sale(
    session: AsyncSession, *, business_id: uuid.UUID, sale_id: uuid.UUID
) -> list[InventoryMovement]:
    result = await session.scalars(
        select(InventoryMovement)
        .where(
            InventoryMovement.business_id == business_id,
            InventoryMovement.sale_id == sale_id,
        )
        .order_by(InventoryMovement.created_at, InventoryMovement.id)
    )
    return list(result)


MAX_LIST_LIMIT = 500


async def list_movements(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    product_id: uuid.UUID | None = None,
    movement_type: MovementType | None = None,
    occurred_from: datetime | None = None,
    occurred_until: datetime | None = None,
    limit: int = MAX_LIST_LIMIT,
) -> list[InventoryMovement]:
    """Movement history, newest first by posting order (`created_at`, then id).

    `quantity_after` was computed in that order; `occurred_at` (the reporting time,
    which may be backdated) is only a filter here, never the ordering key.
    """
    stmt = select(InventoryMovement).where(InventoryMovement.business_id == business_id)
    if product_id is not None:
        stmt = stmt.where(InventoryMovement.product_id == product_id)
    if movement_type is not None:
        stmt = stmt.where(InventoryMovement.movement_type == movement_type)
    if occurred_from is not None:
        stmt = stmt.where(InventoryMovement.occurred_at >= occurred_from)
    if occurred_until is not None:
        stmt = stmt.where(InventoryMovement.occurred_at < occurred_until)
    stmt = stmt.order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc()).limit(
        min(limit, MAX_LIST_LIMIT)
    )
    return list(await session.scalars(stmt))


async def count_movements_for_product(
    session: AsyncSession, *, business_id: uuid.UUID, product_id: uuid.UUID
) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(InventoryMovement)
        .where(
            InventoryMovement.business_id == business_id,
            InventoryMovement.product_id == product_id,
        )
    )
    return int(count or 0)


async def ledger_totals(session: AsyncSession, business_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    """Σ quantity_delta per product — what `products.stock_quantity` caches (BR-11)."""
    rows = await session.execute(
        select(InventoryMovement.product_id, func.sum(InventoryMovement.quantity_delta))
        .where(InventoryMovement.business_id == business_id)
        .group_by(InventoryMovement.product_id)
    )
    return {product_id: Decimal(total) for product_id, total in rows}


async def ledger_totals_for_product(
    session: AsyncSession, *, business_id: uuid.UUID, product_id: uuid.UUID
) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(InventoryMovement.quantity_delta), 0)).where(
            InventoryMovement.business_id == business_id,
            InventoryMovement.product_id == product_id,
        )
    )
    return Decimal(total or 0).quantize(Decimal("0.001"))


async def list_low_stock(
    session: AsyncSession, business_id: uuid.UUID, *, default_threshold: Decimal, limit: int
) -> list[tuple[Product, Decimal]]:
    """Active, tracked products at or below their threshold (own or the business default)."""
    threshold = func.coalesce(Product.low_stock_threshold, default_threshold)
    stmt = (
        select(Product, threshold)
        .where(
            Product.business_id == business_id,
            Product.is_active.is_(True),
            Product.track_inventory.is_(True),
            Product.stock_quantity <= threshold,
        )
        .order_by((Product.stock_quantity - threshold).asc(), func.lower(Product.name), Product.id)
        .limit(min(limit, MAX_LIST_LIMIT))
    )
    rows = await session.execute(stmt)
    return [(product, Decimal(value).quantize(Decimal("0.001"))) for product, value in rows]
