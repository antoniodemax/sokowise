"""Expense analytics and the financial overview (PRD FR-I1, FR-I6, BR-6, BR-10, BR-15)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import error_code
from tests.db.credit_helpers import db_balance
from tests.db.isolation import Tenant
from tests.db.sales_helpers import make_customer, make_product, sale_payload, sell, stock_of

pytestmark = [pytest.mark.db, pytest.mark.anyio]

D = Decimal
EXPENSES_URL = "/api/v1/expenses"
ANALYTICS = "/api/v1/analytics"
NAIROBI = ZoneInfo("Africa/Nairobi")


def _local(day: Any, hour: int, minute: int = 0) -> str:
    return (
        datetime.combine(day, datetime.min.time(), tzinfo=NAIROBI)
        .replace(hour=hour, minute=minute)
        .astimezone(UTC)
        .isoformat()
    )


async def _expense(
    api: AsyncClient,
    headers: dict[str, str],
    amount: str,
    category: str = "Rent",
    method: str = "MPESA",
    **extra: Any,
) -> dict[str, Any]:
    response = await api.post(
        EXPENSES_URL,
        headers=headers,
        json={"amount": amount, "category": category, "payment_method": method, **extra},
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    body: dict[str, Any] = response.json()
    return body


async def _breakdown(api: AsyncClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    response = await api.get(
        f"{ANALYTICS}/expenses", headers=headers, params=params or {"period": "today"}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    body: dict[str, Any] = response.json()
    return body


async def _summary(api: AsyncClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    response = await api.get(
        f"{ANALYTICS}/summary", headers=headers, params=params or {"period": "today"}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_empty_breakdown(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    body = await _breakdown(api, a.owner)
    assert body["total"] == "0.00" and body["count"] == 0 and body["by_category"] == []
    assert body["by_method"] == {"CASH": "0.00", "MPESA": "0.00"}
    assert body["period"]["timezone"] == "Africa/Nairobi"


async def test_breakdown_by_category_and_method(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    await _expense(api, a.owner, "5000", "Rent", "MPESA")
    await _expense(api, a.owner, "300", "transport", "CASH")
    await _expense(api, a.owner, "200.50", "Transport ", "MPESA")
    deleted = await _expense(api, a.owner, "999", "Rent", "CASH")
    await api.delete(f"{EXPENSES_URL}/{deleted['id']}", headers=a.owner)
    await _expense(api, b.owner, "7777", "Rent", "CASH")
    body = await _breakdown(api, a.owner)
    assert (body["total"], body["count"]) == ("5500.50", 3)
    assert body["by_category"] == [
        {"key": "RENT", "total": "5000.00", "count": 1},
        {"key": "TRANSPORT", "total": "500.50", "count": 2},
    ]
    assert body["by_method"] == {"CASH": "300.00", "MPESA": "5200.50"}
    assert (
        sum(D(g["total"]) for g in body["by_category"])
        == D(body["total"])
        == sum(D(v) for v in body["by_method"].values())
    )
    assert (await _breakdown(api, b.owner))["total"] == "7777.00"


async def test_periods_and_nairobi_boundary(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    today = datetime.now(NAIROBI).date()
    d1 = today - timedelta(days=4)
    d2 = d1 + timedelta(days=1)
    await _expense(api, a.owner, "100", incurred_at=_local(d1, 23, 30))  # 20:30 UTC on d1
    await _expense(
        api, a.owner, "200", incurred_at=_local(d2, 0, 30)
    )  # 21:30 UTC on d1, but d2 locally
    first = await _breakdown(
        api, a.owner, period="custom", date_from=d1.isoformat(), date_to=d1.isoformat()
    )
    second = await _breakdown(
        api, a.owner, period="custom", date_from=d2.isoformat(), date_to=d2.isoformat()
    )
    both = await _breakdown(
        api, a.owner, period="custom", date_from=d1.isoformat(), date_to=d2.isoformat()
    )
    assert (first["total"], second["total"], both["total"]) == ("100.00", "200.00", "300.00")
    assert (await _breakdown(api, a.owner, period="today"))["total"] == "0.00"
    assert (
        await _summary(
            api, a.owner, period="custom", date_from=d1.isoformat(), date_to=d1.isoformat()
        )
    )["expenses"] == "100.00"
    bad = await api.get(f"{ANALYTICS}/expenses", headers=a.owner, params={"period": "custom"})
    assert bad.status_code == 422 and error_code(bad) == "INVALID_PERIOD"


async def test_timeseries_carries_expenses_and_net_profit_per_bucket(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, price="100", cost="40", stock="100")
    today = datetime.now(NAIROBI).date()
    d1 = today - timedelta(days=2)
    await sell(
        api, a.owner, sale_payload([(p["id"], "2")], [("CASH", "200")], sold_at=_local(d1, 10))
    )
    await _expense(api, a.owner, "50", incurred_at=_local(d1, 12))
    await _expense(api, a.owner, "30")  # today, no sale today
    params = {"period": "custom", "date_from": d1.isoformat(), "date_to": today.isoformat()}
    buckets = (
        await api.get(
            f"{ANALYTICS}/timeseries", headers=a.owner, params={**params, "granularity": "day"}
        )
    ).json()["buckets"]
    assert [
        (b["bucket_start"], b["revenue"], b["gross_profit"], b["expenses"], b["net_profit"])
        for b in buckets
    ] == [
        (d1.isoformat(), "200.00", "120.00", "50.00", "70.00"),
        (today.isoformat(), "0.00", "0.00", "30.00", "-30.00"),
    ]
    weekly = (
        await api.get(
            f"{ANALYTICS}/timeseries", headers=a.owner, params={**params, "granularity": "week"}
        )
    ).json()["buckets"]
    assert sum(D(b["expenses"]) for b in weekly) == D("80.00")
    monthly = (
        await api.get(
            f"{ANALYTICS}/timeseries", headers=a.owner, params={**params, "granularity": "month"}
        )
    ).json()["buckets"]
    assert sum(D(b["net_profit"]) for b in monthly) == D("40.00")


async def test_financial_overview_separates_every_concept(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """The Phase 8/9 scenario plus a KSh 400 expense, then a void (end-to-end trace)."""
    a, _ = tenants
    product = await make_product(api, a.owner, price="500", cost="300", stock="10")
    customer = await make_customer(api, a.owner, credit_limit="5000")
    await sell(api, a.owner, sale_payload([(product["id"], "2")], [("CASH", "1000")]))
    credit_sale = await sell(
        api,
        a.owner,
        sale_payload([(product["id"], "3")], [("CREDIT", "1500")], customer_id=customer["id"]),
    )
    assert (
        await api.post(
            f"/api/v1/customers/{customer['id']}/repayments",
            headers=a.owner,
            json={"amount": "500", "payment_method": "CASH"},
        )
    ).status_code == 201
    before = await _summary(api, a.owner)

    await _expense(api, a.owner, "400", "Transport", "CASH")
    s = await _summary(api, a.owner)
    assert (s["revenue"], s["cash_collected_total"], s["receivables_outstanding"]) == (
        "2500.00",
        "1500.00",
        "1000.00",
    )
    assert (s["cogs"], s["gross_profit"], s["expenses"], s["net_profit"]) == (
        "1500.00",
        "1000.00",
        "400.00",
        "600.00",
    )
    # The expense changed nothing above the gross-profit line, nor stock, nor the balance.
    for key in (
        "sales_count",
        "revenue",
        "discounts",
        "cogs",
        "gross_profit",
        "tender_split",
        "cash_collected",
        "cash_collected_total",
        "receivables_outstanding",
    ):
        assert s[key] == before[key], key
    assert before["expenses"] == "0.00" and before["net_profit"] == "1000.00"
    assert await stock_of(db_session, product["id"]) == D("5.000")
    assert await db_balance(db_session, customer["id"]) == (D("1000.00"), D("1000.00"))
    assert (await _breakdown(api, a.owner))["by_method"] == {"CASH": "400.00", "MPESA": "0.00"}

    # Void the credit sale: revenue/COGS/gross profit drop, expenses stay, net follows.
    assert (
        await api.post(
            f"/api/v1/sales/{credit_sale['id']}/void", headers=a.owner, json={"reason": "returned"}
        )
    ).status_code == 200
    s = await _summary(api, a.owner)
    assert (s["revenue"], s["cogs"], s["gross_profit"], s["expenses"], s["net_profit"]) == (
        "1000.00",
        "600.00",
        "400.00",
        "400.00",
        "0.00",
    )
    assert (s["cash_collected_total"], s["receivables_outstanding"]) == ("1500.00", "0.00")
    assert await stock_of(db_session, product["id"]) == D("8.000")


async def test_restocks_are_not_expenses(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    """BR-6: stock purchases are inventory events; they never reach the expense figures."""
    a, _ = tenants
    p = await make_product(api, a.owner, stock="1", cost="300")
    assert (
        await api.post(
            "/api/v1/inventory/restock",
            headers=a.owner,
            json={"product_id": p["id"], "quantity": "10", "unit_cost": "280"},
        )
    ).status_code == 201
    s = await _summary(api, a.owner)
    assert s["expenses"] == "0.00" and (await _breakdown(api, a.owner))["count"] == 0


async def test_expense_analytics_are_owner_only_and_isolated(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    assert a.staff is not None
    await _expense(api, b.owner, "123", "Beta rent")
    assert (await api.get(f"{ANALYTICS}/expenses", headers=a.staff)).status_code == 403
    assert (await api.get(f"{ANALYTICS}/expenses")).status_code == 401
    mine = await _breakdown(api, a.owner)
    assert mine["total"] == "0.00" and "BETA" not in str(mine)
    spoofed = await api.get(
        f"{ANALYTICS}/expenses",
        headers=a.owner,
        params={"period": "today", "business_id": b.business_id},
    )
    assert spoofed.status_code == 200 and spoofed.json()["total"] == "0.00"
