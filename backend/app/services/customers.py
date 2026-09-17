"""Customers: create, get, list/search (ROADMAP Phase 6; PRD FR-G1).

Phone uniqueness per business is the database's partial unique index, translated
to 409 `CUSTOMER_PHONE_EXISTS`. The same phone may exist in another business.
Update, archive, PII scrub, repayments, adjustments and the ledger are Phase 7;
nothing here touches `balance`, which only ledger entries move.

No customer field is logged: name, phone and notes are personal data (PRD NFR-7).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import BusinessContext
from app.core.errors import ConflictError, NotFoundError
from app.db.session import transaction
from app.models import Customer
from app.repositories import customers as customer_repo
from app.schemas.customers import CustomerCreateRequest

_PHONE_CONSTRAINT = "uq_customers_business_id_phone"


async def list_customers(
    session: AsyncSession,
    ctx: BusinessContext,
    *,
    query: str | None,
    include_archived: bool,
    limit: int,
) -> list[Customer]:
    return await customer_repo.list_customers(
        session, ctx.business_id, query=query, include_archived=include_archived, limit=limit
    )


async def get_customer(
    session: AsyncSession, ctx: BusinessContext, customer_id: uuid.UUID
) -> Customer:
    customer = await customer_repo.get_customer(
        session, business_id=ctx.business_id, customer_id=customer_id
    )
    if customer is None:
        raise NotFoundError("Customer not found")
    return customer


async def create_customer(
    session: AsyncSession, ctx: BusinessContext, data: CustomerCreateRequest
) -> Customer:
    customer = Customer(
        business_id=ctx.business_id,
        name=data.name,
        phone=data.phone,
        notes=data.notes,
        credit_limit=data.credit_limit,
        balance=Decimal("0.00"),
        is_active=True,
    )
    try:
        async with transaction(session):
            session.add(customer)
            await session.flush()
            await session.refresh(customer)
    except IntegrityError as exc:
        if _PHONE_CONSTRAINT in str(exc.orig):
            raise ConflictError(
                "A customer with this phone number already exists", code="CUSTOMER_PHONE_EXISTS"
            ) from None
        raise
    return customer


async def iter_export(session: AsyncSession, ctx: BusinessContext) -> AsyncIterator[Customer]:
    """OWNER export (PRD NFR-12): every customer, archived included, oldest first."""
    after: tuple[datetime, uuid.UUID] | None = None
    while True:
        batch = await customer_repo.export_batch(session, ctx.business_id, after=after)
        for customer in batch:
            yield customer
        if len(batch) < customer_repo.EXPORT_BATCH:
            return
        after = (batch[-1].created_at, batch[-1].id)
