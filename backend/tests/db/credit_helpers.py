"""Helpers for the credit-ledger tests: post CHARGE entries the way the sales phase will."""

import uuid
from decimal import Decimal
from http import HTTPStatus
from typing import Any

from app.core.context import BusinessContext
from app.db.session import transaction
from app.models import BusinessMembership, CreditTransaction, Customer
from app.models.enums import CreditEntryType
from app.repositories import credit as credit_repo
from app.repositories import customers as customer_repo
from app.services import credit as credit_service
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.isolation import Tenant

CUSTOMERS_URL = "/api/v1/customers"
DEBTORS_URL = "/api/v1/debtors"


async def create_customer(
    api: AsyncClient, headers: dict[str, str], name: str = "Mama Njeri", **fields: Any
) -> dict[str, Any]:
    response = await api.post(CUSTOMERS_URL, headers=headers, json={"name": name, **fields})
    assert response.status_code == HTTPStatus.CREATED, response.text
    body: dict[str, Any] = response.json()
    return body


async def owner_context(session: AsyncSession, tenant: Tenant) -> BusinessContext:
    membership = (
        await session.scalars(
            select(BusinessMembership).where(
                BusinessMembership.user_id == uuid.UUID(tenant.owner_user_id),
                BusinessMembership.business_id == uuid.UUID(tenant.business_id),
            )
        )
    ).one()
    return BusinessContext(
        user_id=membership.user_id,
        business_id=membership.business_id,
        membership_id=membership.id,
        role=membership.role,
        timezone="Africa/Nairobi",
        settings={},
    )


async def charge(
    session: AsyncSession, tenant: Tenant, customer_id: str, amount: str
) -> CreditTransaction:
    """A CHARGE as a credit sale will post it: locked customer, one transaction."""
    ctx = await owner_context(session, tenant)
    async with transaction(session):
        customer = await customer_repo.get_customer_for_update(
            session, business_id=ctx.business_id, customer_id=uuid.UUID(customer_id)
        )
        assert customer is not None
        return await credit_service.post_entry(
            session,
            ctx,
            customer=customer,
            entry_type=CreditEntryType.CHARGE,
            amount=Decimal(amount),
        )


async def db_balance(session: AsyncSession, customer_id: str) -> tuple[Decimal, Decimal]:
    """(cache, ledger sum) — they must always agree."""
    customer = await session.get(Customer, uuid.UUID(customer_id))
    assert customer is not None
    await session.refresh(customer)
    total = await credit_repo.sum_entries(
        session, business_id=customer.business_id, customer_id=customer.id
    )
    return customer.balance, total


async def repay(
    api: AsyncClient,
    headers: dict[str, str],
    customer_id: str,
    amount: str,
    method: str = "CASH",
    **extra: Any,
) -> Any:
    return await api.post(
        f"{CUSTOMERS_URL}/{customer_id}/repayments",
        headers=headers,
        json={"amount": amount, "payment_method": method, **extra},
    )


async def adjust(
    api: AsyncClient,
    headers: dict[str, str],
    customer_id: str,
    amount: str,
    direction: str,
    reason: str = "stock-take correction",
    **extra: Any,
) -> Any:
    return await api.post(
        f"{CUSTOMERS_URL}/{customer_id}/adjustments",
        headers=headers,
        json={"amount": amount, "direction": direction, "reason": reason, **extra},
    )
