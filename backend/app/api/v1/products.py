"""Products (ROADMAP Phase 5; PRD FR-D1-FR-D6, §16).

Members (OWNER and STAFF) read the catalogue — sale entry needs it; only owners
create, edit, price or archive products.
"""

import uuid
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_info, require_member, require_owner
from app.core.context import BusinessContext, ClientInfo
from app.db.session import get_session
from app.repositories.products import MAX_LIST_LIMIT
from app.schemas.catalog import ProductCreateRequest, ProductOut, ProductUpdateRequest
from app.services import products as products_service

router = APIRouter(prefix="/products", tags=["products"])

MemberCtx = Annotated[BusinessContext, Depends(require_member)]
OwnerCtx = Annotated[BusinessContext, Depends(require_owner)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClientDep = Annotated[ClientInfo, Depends(get_client_info)]


@router.get("", response_model=list[ProductOut])
async def list_products(
    ctx: MemberCtx,
    session: SessionDep,
    q: Annotated[
        str | None, Query(max_length=120, description="prefix of name, SKU or barcode")
    ] = None,
    category_id: uuid.UUID | None = None,
    include_archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = MAX_LIST_LIMIT,
) -> list[ProductOut]:
    rows = await products_service.list_products(
        session,
        ctx,
        query=q.strip() if q else None,
        category_id=category_id,
        include_archived=include_archived,
        limit=limit,
    )
    return [ProductOut.model_validate(row, from_attributes=True) for row in rows]


@router.post("", status_code=HTTPStatus.CREATED, response_model=ProductOut)
async def create_product(
    payload: ProductCreateRequest, ctx: OwnerCtx, session: SessionDep, client: ClientDep
) -> ProductOut:
    row = await products_service.create_product(session, ctx, payload, client)
    return ProductOut.model_validate(row, from_attributes=True)


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: uuid.UUID, ctx: MemberCtx, session: SessionDep) -> ProductOut:
    row = await products_service.get_product(session, ctx, product_id)
    return ProductOut.model_validate(row, from_attributes=True)


@router.patch("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdateRequest,
    ctx: OwnerCtx,
    session: SessionDep,
    client: ClientDep,
) -> ProductOut:
    row = await products_service.update_product(session, ctx, product_id, payload, client)
    return ProductOut.model_validate(row, from_attributes=True)
