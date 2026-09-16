"""Inventory operations (ROADMAP Phase 5, inventory half; PRD FR-E, §16).

Restock: OWNER, or STAFF when the business setting `staff_can_restock` is on (the
service checks). Adjustments, opening stock and cache recomputation: OWNER.
Movement history and the low-stock list: members.
"""

import uuid
from datetime import datetime
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_info, require_member, require_owner
from app.core.context import BusinessContext, ClientInfo
from app.db.session import get_session
from app.models.enums import MovementType
from app.repositories.inventory import MAX_LIST_LIMIT
from app.schemas.inventory import (
    AdjustmentRequest,
    InitialStockRequest,
    LowStockProductOut,
    MovementOut,
    RecomputeRequest,
    RecomputeResponse,
    RestockRequest,
    StockDiscrepancyOut,
)
from app.services import inventory as inventory_service

router = APIRouter(prefix="/inventory", tags=["inventory"])

MemberCtx = Annotated[BusinessContext, Depends(require_member)]
OwnerCtx = Annotated[BusinessContext, Depends(require_owner)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClientDep = Annotated[ClientInfo, Depends(get_client_info)]


@router.post("/restock", status_code=HTTPStatus.CREATED, response_model=MovementOut)
async def restock(
    payload: RestockRequest, ctx: MemberCtx, session: SessionDep, client: ClientDep
) -> MovementOut:
    movement = await inventory_service.restock(session, ctx, payload, client)
    return MovementOut.model_validate(movement, from_attributes=True)


@router.post("/adjust", status_code=HTTPStatus.CREATED, response_model=MovementOut)
async def adjust(
    payload: AdjustmentRequest, ctx: OwnerCtx, session: SessionDep, client: ClientDep
) -> MovementOut:
    movement = await inventory_service.adjust(session, ctx, payload, client)
    return MovementOut.model_validate(movement, from_attributes=True)


@router.post("/initial", status_code=HTTPStatus.CREATED, response_model=MovementOut)
async def set_initial_stock(
    payload: InitialStockRequest, ctx: OwnerCtx, session: SessionDep, client: ClientDep
) -> MovementOut:
    movement = await inventory_service.set_initial_stock(session, ctx, payload, client)
    return MovementOut.model_validate(movement, from_attributes=True)


@router.get("/movements", response_model=list[MovementOut])
async def list_movements(
    ctx: MemberCtx,
    session: SessionDep,
    product_id: uuid.UUID | None = None,
    movement_type: MovementType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 100,
) -> list[MovementOut]:
    rows = await inventory_service.list_movements(
        session,
        ctx,
        product_id=product_id,
        movement_type=movement_type,
        occurred_from=date_from,
        occurred_until=date_to,
        limit=limit,
    )
    return [MovementOut.model_validate(row, from_attributes=True) for row in rows]


@router.get("/low-stock", response_model=list[LowStockProductOut])
async def list_low_stock(
    ctx: MemberCtx,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 100,
) -> list[LowStockProductOut]:
    rows = await inventory_service.list_low_stock(session, ctx, limit=limit)
    return [
        LowStockProductOut(
            product_id=product.id,
            name=product.name,
            sku=product.sku,
            unit=product.unit.value,
            stock_quantity=product.stock_quantity,
            threshold=threshold,
        )
        for product, threshold in rows
    ]


@router.post("/recompute", response_model=RecomputeResponse)
async def recompute_stock(
    payload: RecomputeRequest, ctx: OwnerCtx, session: SessionDep, client: ClientDep
) -> RecomputeResponse:
    result = await inventory_service.recompute_stock(
        session, ctx, apply=payload.apply, client=client
    )
    return RecomputeResponse(
        products_checked=result.products_checked,
        discrepancies=[
            StockDiscrepancyOut(
                product_id=d.product_id,
                cached_stock=d.cached_stock,
                ledger_stock=d.ledger_stock,
                repaired=d.repaired,
            )
            for d in result.discrepancies
        ],
        applied=result.applied,
    )
