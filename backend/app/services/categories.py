"""Categories: simple per-business labels (PRD FR-D4).

No archive state exists for categories (DATA_MAPPING §3.5); a category can be
deleted only while no product — active or archived — is labelled with it, so
history never loses a label.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import BusinessContext
from app.core.errors import ConflictError, NotFoundError
from app.db.session import transaction
from app.models import Category
from app.repositories import categories as category_repo
from app.schemas.catalog import CategoryCreateRequest, CategoryUpdateRequest

_NAME_CONSTRAINT = "uq_categories_business_id_lower_name"


def _exists() -> ConflictError:
    return ConflictError("A category with this name already exists", code="CATEGORY_EXISTS")


async def list_categories(session: AsyncSession, ctx: BusinessContext) -> list[Category]:
    return await category_repo.list_categories(session, ctx.business_id)


async def get_category(
    session: AsyncSession, ctx: BusinessContext, category_id: uuid.UUID
) -> Category:
    category = await category_repo.get_category(
        session, business_id=ctx.business_id, category_id=category_id
    )
    if category is None:
        raise NotFoundError("Category not found")
    return category


async def create_category(
    session: AsyncSession, ctx: BusinessContext, data: CategoryCreateRequest
) -> Category:
    category = Category(business_id=ctx.business_id, name=data.name)
    try:
        async with transaction(session):
            session.add(category)
            await session.flush()
            await session.refresh(category)
    except IntegrityError as exc:
        if _NAME_CONSTRAINT in str(exc.orig):
            raise _exists() from None
        raise
    return category


async def update_category(
    session: AsyncSession, ctx: BusinessContext, category_id: uuid.UUID, data: CategoryUpdateRequest
) -> Category:
    try:
        async with transaction(session):
            category = await get_category(session, ctx, category_id)
            category.name = data.name
            await session.flush()
            # updated_at is set by the database on UPDATE; load it before the response reads it.
            await session.refresh(category)
    except IntegrityError as exc:
        if _NAME_CONSTRAINT in str(exc.orig):
            raise _exists() from None
        raise
    return category


async def delete_category(
    session: AsyncSession, ctx: BusinessContext, category_id: uuid.UUID
) -> None:
    async with transaction(session):
        category = await get_category(session, ctx, category_id)
        in_use = await category_repo.count_products_in_category(
            session, business_id=ctx.business_id, category_id=category.id
        )
        if in_use:
            raise ConflictError(
                "This category is still used by products; move them first",
                code="CATEGORY_IN_USE",
                details={"products": in_use},
            )
        await session.delete(category)
        await session.flush()
