"""`POST /customers/recompute`: the ledger is the truth for `customers.balance` (PRD BR-7)."""

import uuid
from decimal import Decimal
from http import HTTPStatus

import pytest
from app.models import AuditLog, CreditTransaction, Customer
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.isolation import Tenant
from tests.db.sales_helpers import CUSTOMERS_URL, make_customer, make_product, sale_payload, sell

pytestmark = [pytest.mark.db, pytest.mark.anyio]

URL = f"{CUSTOMERS_URL}/recompute"


async def test_recompute_reports_and_repairs_balance_drift(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner, stock="10")
    c = await make_customer(api, a.owner)
    await sell(
        api, a.owner, sale_payload([(p["id"], "2")], [("CREDIT", "1000")], customer_id=c["id"])
    )
    repay = await api.post(
        f"{CUSTOMERS_URL}/{c['id']}/repayments",
        headers=a.owner,
        json={"amount": "250", "payment_method": "CASH"},
    )
    assert repay.status_code == HTTPStatus.CREATED, repay.text
    other = await make_customer(api, b.owner, name="Other tenant")

    assert (await api.post(URL, headers=a.staff, json={"apply": True})).status_code == 403
    clean = await api.post(URL, headers=a.owner, json={"apply": False})
    assert clean.status_code == HTTPStatus.OK and clean.json() == {
        "customers_checked": 1,
        "discrepancies": [],
        "applied": False,
    }

    # Corrupt the cache behind the API's back (and another tenant's, which must be untouched).
    customer = await db_session.get(Customer, uuid.UUID(c["id"]))
    foreign = await db_session.get(Customer, uuid.UUID(other["id"]))
    assert customer is not None and foreign is not None
    customer.balance = Decimal("999.00")
    foreign.balance = Decimal("5.00")
    await db_session.flush()

    report = (await api.post(URL, headers=a.owner, json={"apply": False})).json()
    assert report["discrepancies"] == [
        {
            "customer_id": c["id"],
            "cached_balance": "999.00",
            "ledger_balance": "750.00",
            "repaired": False,
        }
    ]
    await db_session.refresh(customer)
    assert customer.balance == Decimal("999.00")  # dry run changed nothing

    fixed = (await api.post(URL, headers=a.owner, json={"apply": True})).json()
    assert fixed["applied"] is True and fixed["discrepancies"][0]["repaired"] is True
    await db_session.refresh(customer)
    await db_session.refresh(foreign)
    assert customer.balance == Decimal("750.00")
    assert foreign.balance == Decimal("5.00")  # other tenant untouched
    # No ledger entry was written by the repair, and the repair is audited.
    entries = list(
        await db_session.scalars(
            select(CreditTransaction).where(CreditTransaction.customer_id == customer.id)
        )
    )
    assert len(entries) == 2
    audits = list(
        await db_session.scalars(
            select(AuditLog)
            .where(
                AuditLog.business_id == customer.business_id, AuditLog.action == "credit.recompute"
            )
            .execution_options(populate_existing=True)
        )
    )
    assert len(audits) == 1
    assert audits[0].before == {"balance": "999.00"} and audits[0].after == {"balance": "750.00"}
    assert (await api.post(URL, headers=a.owner, json={"apply": False})).json()[
        "discrepancies"
    ] == []


async def test_recompute_rejects_unknown_fields(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    bad = await api.post(URL, headers=a.owner, json={"apply": True, "business_id": "x"})
    assert bad.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
