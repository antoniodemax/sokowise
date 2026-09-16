"""Customers (ROADMAP Phase 6; PRD FR-G1, §16).

OWNER and STAFF both read and create customers ("Create / edit customers, record
repayment" is a member permission): an attendant must be able to open a credit
account mid-sale. Search is the `q` parameter of the list, so no path segment
can collide with a customer id.
"""

import uuid
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_member
from app.core.context import BusinessContext
from app.db.session import get_session
from app.repositories.customers import MAX_LIST_LIMIT
from app.schemas.customers import CustomerCreateRequest, CustomerOut
from app.services import customers as customers_service

router = APIRouter(prefix="/customers", tags=["customers"])

MemberCtx = Annotated[BusinessContext, Depends(require_member)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[CustomerOut])
async def list_customers(
    ctx: MemberCtx,
    session: SessionDep,
    q: Annotated[
        str | None, Query(max_length=120, description="part of the name, or a phone prefix")
    ] = None,
    include_archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = MAX_LIST_LIMIT,
) -> list[CustomerOut]:
    rows = await customers_service.list_customers(
        session,
        ctx,
        query=q.strip() if q else None,
        include_archived=include_archived,
        limit=limit,
    )
    return [CustomerOut.model_validate(row, from_attributes=True) for row in rows]


@router.post("", status_code=HTTPStatus.CREATED, response_model=CustomerOut)
async def create_customer(
    payload: CustomerCreateRequest, ctx: MemberCtx, session: SessionDep
) -> CustomerOut:
    row = await customers_service.create_customer(session, ctx, payload)
    return CustomerOut.model_validate(row, from_attributes=True)


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: uuid.UUID, ctx: MemberCtx, session: SessionDep) -> CustomerOut:
    row = await customers_service.get_customer(session, ctx, customer_id)
    return CustomerOut.model_validate(row, from_attributes=True)
