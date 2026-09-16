"""inventory_movements — append-only (docs/DATA_MAPPING.md §3.7).

Rows are only ever added, through `services.inventory`, which also maintains the
`products.stock_quantity` cache in the same transaction.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InventoryMovement


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
