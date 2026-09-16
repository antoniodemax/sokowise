"""The end-to-end accounting trace from the phase brief, executed against the API and DB."""

import uuid
from decimal import Decimal
from http import HTTPStatus

import pytest
from app.models import AuditLog, CreditTransaction, InventoryMovement, Payment, Sale, SaleItem
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.credit_helpers import db_balance
from tests.db.isolation import Tenant
from tests.db.sales_helpers import make_customer, make_product, sale_payload, sell, stock_of

pytestmark = [pytest.mark.db, pytest.mark.anyio]

D = Decimal


async def _figures(session: AsyncSession, business_id: str) -> dict[str, Decimal]:
    """Revenue / cash collected / COGS / gross profit per BR-15 and BR-5, straight from rows."""
    bid = uuid.UUID(business_id)
    sales = (
        await session.scalars(
            select(Sale)
            .where(Sale.business_id == bid, Sale.status == "COMPLETED")
            .execution_options(populate_existing=True)
        )
    ).all()
    completed = {s.id for s in sales}
    items = [
        i
        for i in (await session.scalars(select(SaleItem).where(SaleItem.business_id == bid))).all()
        if i.sale_id in completed
    ]
    payments = [
        p
        for p in (await session.scalars(select(Payment).where(Payment.business_id == bid))).all()
        if p.sale_id in completed
    ]
    repayments = (
        await session.scalars(
            select(CreditTransaction).where(
                CreditTransaction.business_id == bid, CreditTransaction.entry_type == "REPAYMENT"
            )
        )
    ).all()
    revenue = sum((s.total_amount for s in sales), D("0"))
    cash = sum(
        (
            p.amount
            for p in payments
            if p.method.value != "CREDIT" and p.status.value == "CONFIRMED"
        ),
        D("0"),
    )
    cash += sum((-r.amount for r in repayments), D("0"))
    cogs = sum((i.quantity * i.unit_cost for i in items if i.unit_cost is not None), D("0"))
    net_lines = sum((i.line_total - i.discount_allocated for i in items), D("0"))
    return {
        "revenue": revenue,
        "cash_collected": cash,
        "cogs": cogs,
        "gross_profit": net_lines - cogs,
    }


async def test_accounting_trace(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    product = await make_product(api, a.owner, price="500", cost="300", stock="10")
    customer = await make_customer(api, a.owner, credit_limit="5000")
    assert await stock_of(db_session, product["id"]) == D("10.000")
    assert await db_balance(db_session, customer["id"]) == (D("0.00"), D("0.00"))

    cash_sale = await sell(api, a.owner, sale_payload([(product["id"], "2")], [("CASH", "1000")]))
    assert cash_sale["total_amount"] == "1000.00"
    assert await stock_of(db_session, product["id"]) == D("8.000")
    assert await db_balance(db_session, customer["id"]) == (D("0.00"), D("0.00"))
    assert await _figures(db_session, a.business_id) == {
        "revenue": D("1000.00"),
        "cash_collected": D("1000.00"),
        "cogs": D("600.00"),
        "gross_profit": D("400.00"),
    }

    credit_sale = await sell(
        api,
        a.owner,
        sale_payload([(product["id"], "3")], [("CREDIT", "1500")], customer_id=customer["id"]),
    )
    assert credit_sale["total_amount"] == "1500.00"
    assert await stock_of(db_session, product["id"]) == D("5.000")
    assert await db_balance(db_session, customer["id"]) == (D("1500.00"), D("1500.00"))
    figures = await _figures(db_session, a.business_id)
    assert figures == {
        "revenue": D("2500.00"),  # 1000 + 1500: the credit sale is revenue
        "cash_collected": D("1000.00"),  # but not cash
        "cogs": D("1500.00"),  # 600 + 900
        "gross_profit": D("1000.00"),  # 400 + 600
    }
    charge = (
        await db_session.scalars(
            select(CreditTransaction).where(
                CreditTransaction.sale_id == uuid.UUID(credit_sale["id"])
            )
        )
    ).one()
    assert (charge.entry_type.value, charge.amount, charge.balance_after) == (
        "CHARGE",
        D("1500.00"),
        D("1500.00"),
    )

    repayment = await api.post(
        f"/api/v1/customers/{customer['id']}/repayments",
        headers=a.owner,
        json={"amount": "500", "payment_method": "CASH"},
    )
    assert repayment.status_code == HTTPStatus.CREATED
    assert await db_balance(db_session, customer["id"]) == (D("1000.00"), D("1000.00"))
    figures = await _figures(db_session, a.business_id)
    assert figures["revenue"] == D("2500.00")  # unchanged: a repayment is never revenue
    assert figures["cash_collected"] == D("1500.00")  # 1000 + the 500 repayment
    assert figures["cogs"] == D("1500.00") and figures["gross_profit"] == D("1000.00")

    # Row-level state after everything.
    bid = uuid.UUID(a.business_id)
    assert len((await db_session.scalars(select(Sale).where(Sale.business_id == bid))).all()) == 2
    assert (
        len((await db_session.scalars(select(SaleItem).where(SaleItem.business_id == bid))).all())
        == 2
    )
    payments = (await db_session.scalars(select(Payment).where(Payment.business_id == bid))).all()
    assert sorted((p.method.value, p.amount) for p in payments) == [
        ("CASH", D("1000.00")),
        ("CREDIT", D("1500.00")),
    ]
    movements = (
        await db_session.scalars(
            select(InventoryMovement)
            .where(InventoryMovement.business_id == bid)
            .execution_options(populate_existing=True)
        )
    ).all()
    assert sorted((m.movement_type.value, m.quantity_delta) for m in movements) == [
        ("INITIAL", D("10.000")),
        ("SALE", D("-3.000")),
        ("SALE", D("-2.000")),
    ]
    ledger = (
        await db_session.scalars(
            select(CreditTransaction)
            .where(CreditTransaction.business_id == bid)
            .execution_options(populate_existing=True)
        )
    ).all()
    assert sorted((e.entry_type.value, e.amount) for e in ledger) == [
        ("CHARGE", D("1500.00")),
        ("REPAYMENT", D("-500.00")),
    ]
    audits = (await db_session.scalars(select(AuditLog).where(AuditLog.business_id == bid))).all()
    assert [r.action for r in audits] == ["credit.repayment"]  # sales themselves are not audited
