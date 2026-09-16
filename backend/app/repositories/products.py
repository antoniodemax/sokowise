"""products (docs/DATA_MAPPING.md §3.6). Every query is scoped by `business_id`.

`get_product_for_update` takes the row lock that inventory movements need (BR-11):
every change to `stock_quantity` happens under it, in the same transaction as the
movement row.
"""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product

MAX_LIST_LIMIT = 500


async def list_products(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    query: str | None = None,
    category_id: uuid.UUID | None = None,
    include_archived: bool = False,
    limit: int = MAX_LIST_LIMIT,
) -> list[Product]:
    """Catalogue listing / search (PRD FR-D5): case-insensitive prefix on name, SKU or barcode."""
    stmt = select(Product).where(Product.business_id == business_id)
    if not include_archived:
        stmt = stmt.where(Product.is_active.is_(True))
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)
    if query:
        prefix = _escape_like(query.lower()) + "%"
        stmt = stmt.where(
            or_(
                func.lower(Product.name).like(prefix, escape="\\"),
                func.lower(Product.sku).like(prefix, escape="\\"),
                func.lower(Product.barcode).like(prefix, escape="\\"),
            )
        )
    stmt = stmt.order_by(func.lower(Product.name), Product.id).limit(min(limit, MAX_LIST_LIMIT))
    return list(await session.scalars(stmt))


async def get_product(
    session: AsyncSession, *, business_id: uuid.UUID, product_id: uuid.UUID
) -> Product | None:
    result = await session.scalars(
        select(Product).where(Product.business_id == business_id, Product.id == product_id)
    )
    return result.one_or_none()


async def get_product_for_update(
    session: AsyncSession, *, business_id: uuid.UUID, product_id: uuid.UUID
) -> Product | None:
    """`SELECT … FOR UPDATE` on one product; the lock every stock change must hold."""
    result = await session.scalars(
        select(Product)
        .where(Product.business_id == business_id, Product.id == product_id)
        .with_for_update()
    )
    return result.one_or_none()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
