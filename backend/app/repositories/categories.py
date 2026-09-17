"""categories (docs/DATA_MAPPING.md §3.5). Every query is scoped by `business_id`."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Product

# Bounded like every other listing; a business has nowhere near this many categories.
MAX_LIST_LIMIT = 500


async def list_categories(session: AsyncSession, business_id: uuid.UUID) -> list[Category]:
    result = await session.scalars(
        select(Category)
        .where(Category.business_id == business_id)
        .order_by(func.lower(Category.name), Category.id)
        .limit(MAX_LIST_LIMIT)
    )
    return list(result)


async def get_category(
    session: AsyncSession, *, business_id: uuid.UUID, category_id: uuid.UUID
) -> Category | None:
    result = await session.scalars(
        select(Category).where(Category.business_id == business_id, Category.id == category_id)
    )
    return result.one_or_none()


async def count_products_in_category(
    session: AsyncSession, *, business_id: uuid.UUID, category_id: uuid.UUID
) -> int:
    """Products (active or archived) still labelled with this category."""
    count = await session.scalar(
        select(func.count())
        .select_from(Product)
        .where(Product.business_id == business_id, Product.category_id == category_id)
    )
    return int(count or 0)
