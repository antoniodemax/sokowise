"""Categories (ROADMAP Phase 5; PRD FR-D4). Members read; owners write."""

import uuid
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_member, require_owner
from app.core.context import BusinessContext
from app.db.session import get_session
from app.schemas.catalog import CategoryCreateRequest, CategoryOut, CategoryUpdateRequest
from app.services import categories as categories_service

router = APIRouter(prefix="/categories", tags=["categories"])

MemberCtx = Annotated[BusinessContext, Depends(require_member)]
OwnerCtx = Annotated[BusinessContext, Depends(require_owner)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[CategoryOut])
async def list_categories(ctx: MemberCtx, session: SessionDep) -> list[CategoryOut]:
    rows = await categories_service.list_categories(session, ctx)
    return [CategoryOut.model_validate(row, from_attributes=True) for row in rows]


@router.post("", status_code=HTTPStatus.CREATED, response_model=CategoryOut)
async def create_category(
    payload: CategoryCreateRequest, ctx: OwnerCtx, session: SessionDep
) -> CategoryOut:
    row = await categories_service.create_category(session, ctx, payload)
    return CategoryOut.model_validate(row, from_attributes=True)


@router.get("/{category_id}", response_model=CategoryOut)
async def get_category(category_id: uuid.UUID, ctx: MemberCtx, session: SessionDep) -> CategoryOut:
    row = await categories_service.get_category(session, ctx, category_id)
    return CategoryOut.model_validate(row, from_attributes=True)


@router.patch("/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: uuid.UUID, payload: CategoryUpdateRequest, ctx: OwnerCtx, session: SessionDep
) -> CategoryOut:
    row = await categories_service.update_category(session, ctx, category_id, payload)
    return CategoryOut.model_validate(row, from_attributes=True)


@router.delete("/{category_id}", status_code=HTTPStatus.NO_CONTENT)
async def delete_category(category_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> Response:
    await categories_service.delete_category(session, ctx, category_id)
    return Response(status_code=HTTPStatus.NO_CONTENT)
