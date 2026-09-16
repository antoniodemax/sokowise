"""Debtors: customers who currently owe the business (PRD FR-G4). Members read."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_member
from app.core.context import BusinessContext
from app.db.session import get_session
from app.repositories.credit import MAX_LIST_LIMIT, DebtorSort
from app.schemas.credit import DebtorOut
from app.services import credit as credit_service

router = APIRouter(prefix="/debtors", tags=["customers"])


@router.get("", response_model=list[DebtorOut])
async def list_debtors(
    ctx: Annotated[BusinessContext, Depends(require_member)],
    session: Annotated[AsyncSession, Depends(get_session)],
    sort: Annotated[
        DebtorSort, Query(description="balance (largest first) or age (oldest first)")
    ] = "balance",
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = MAX_LIST_LIMIT,
) -> list[DebtorOut]:
    rows = await credit_service.list_debtors(session, ctx, sort=sort, limit=limit)
    return [
        DebtorOut(
            customer_id=row.customer.id,
            name=row.customer.name,
            phone=row.customer.phone,
            balance=row.customer.balance,
            credit_limit=row.customer.credit_limit,
            oldest_unpaid_charge_at=row.oldest_unpaid_charge_at,
        )
        for row in rows
    ]
