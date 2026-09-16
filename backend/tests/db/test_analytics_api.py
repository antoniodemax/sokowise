"""/api/v1/analytics (PRD FR-I1-FR-I3, BR-10, BR-14, BR-15, BR-16)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.analytics.periods import NamedPeriod, period_for_dates, resolve_period
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import error_code, set_business_active
from tests.db.isolation import Tenant
from tests.db.sales_helpers import (
    PRODUCTS_URL,
    SALES_URL,
    make_customer,
    make_product,
    sale_payload,
    sell,
)

pytestmark = [pytest.mark.db, pytest.mark.anyio]

D = Decimal
URL = "/api/v1/analytics"
NAIROBI = ZoneInfo("Africa/Nairobi")


async def _summary(api: AsyncClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    response = await api.get(
        f"{URL}/summary", headers=headers, params=params or {"period": "today"}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    body: dict[str, Any] = response.json()
    return body


def _iso(local: datetime) -> str:
    return local.astimezone(UTC).isoformat()


# --- period semantics (pure) ---------------------------------------------------------------


def test_periods_are_local_calendar_days_in_the_business_timezone() -> None:
    period = period_for_dates("Africa/Nairobi", date(2026, 9, 16), date(2026, 9, 16))
    assert period.start == datetime(2026, 9, 15, 21, 0, tzinfo=UTC)  # 00:00 EAT
    assert period.end == datetime(2026, 9, 16, 21, 0, tzinfo=UTC)  # next midnight EAT, exclusive
    now = datetime(2026, 9, 16, 22, 30, tzinfo=UTC)  # 01:30 on the 17th in Nairobi
    assert resolve_period("Africa/Nairobi", NamedPeriod.TODAY, now=now).date_from == date(
        2026, 9, 17
    )
    assert resolve_period("UTC", NamedPeriod.TODAY, now=now).date_from == date(2026, 9, 16)
    week = resolve_period("Africa/Nairobi", NamedPeriod.THIS_WEEK, now=now)
    assert (week.date_from, week.date_to) == (date(2026, 9, 14), date(2026, 9, 17))  # Monday..today
    month = resolve_period("Africa/Nairobi", NamedPeriod.THIS_MONTH, now=now)
    assert (month.date_from, month.date_to) == (date(2026, 9, 1), date(2026, 9, 17))
    with pytest.raises(ValueError, match="before"):
        period_for_dates("UTC", date(2026, 9, 2), date(2026, 9, 1))
    with pytest.raises(ValueError, match="required"):
        resolve_period("UTC", NamedPeriod.CUSTOM)


# --- summary ----------------------------------------------------------------------------


async def test_empty_business_has_zero_everything(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    body = await _summary(api, a.owner)
    assert body["period"]["timezone"] == "Africa/Nairobi"
    assert body["sales_count"] == 0 and body["revenue"] == "0.00" and body["gross_profit"] == "0.00"
    assert body["tender_split"] == {"CASH": "0.00", "MPESA": "0.00", "CREDIT": "0.00"}
    assert (
        body["cash_collected"] == {"CASH": "0.00", "MPESA": "0.00"}
        and body["cash_collected_total"] == "0.00"
    )
    assert body["receivables_outstanding"] == "0.00" and body["expenses"] == "0.00"
    assert (await api.get(f"{URL}/products", headers=a.owner)).json() == []
    assert (await api.get(f"{URL}/categories", headers=a.owner)).json() == []
    assert (await api.get(f"{URL}/timeseries", headers=a.owner)).json()["buckets"] == []


async def test_revenue_cash_and_receivables_follow_br15(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, price="500", cost="300", stock="100")
    c = await make_customer(api, a.owner, credit_limit="5000")
    await sell(api, a.owner, sale_payload([(p["id"], "2")], [("CASH", "1000")]))
    await sell(api, a.owner, sale_payload([(p["id"], "1")], [("MPESA", "500")]))
    await sell(
        api, a.owner, sale_payload([(p["id"], "3")], [("CREDIT", "1500")], customer_id=c["id"])
    )
    body = await _summary(api, a.owner)
    assert body["sales_count"] == 3
    assert body["revenue"] == "3000.00"  # credit sale is revenue
    assert body["tender_split"] == {"CASH": "1000.00", "MPESA": "500.00", "CREDIT": "1500.00"}
    assert body["cash_collected"] == {"CASH": "1000.00", "MPESA": "500.00"}  # credit is not cash
    assert body["cash_collected_total"] == "1500.00"
    assert body["receivables_outstanding"] == "1500.00"
    assert (body["cogs"], body["gross_profit"]) == ("1800.00", "1200.00")

    # A repayment raises cash collected (by its method) but never revenue.
    assert (
        await api.post(
            f"/api/v1/customers/{c['id']}/repayments",
            headers=a.owner,
            json={"amount": "700", "payment_method": "MPESA"},
        )
    ).status_code == 201
    body = await _summary(api, a.owner)
    assert body["revenue"] == "3000.00" and body["sales_count"] == 3
    assert body["cash_collected"] == {"CASH": "1000.00", "MPESA": "1200.00"}
    assert body["cash_collected_total"] == "2200.00" and body["receivables_outstanding"] == "800.00"


async def test_voided_sales_are_excluded_everywhere(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, price="500", cost="300", stock="100")
    keep = await sell(api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")]))
    gone = await sell(api, a.owner, sale_payload([(p["id"], "4")], [("MPESA", "2000")]))
    assert (
        await api.post(
            f"{SALES_URL}/{gone['id']}/void", headers=a.owner, json={"reason": "mistake"}
        )
    ).status_code == 200
    body = await _summary(api, a.owner)
    assert (body["sales_count"], body["revenue"], body["cogs"]) == (1, "500.00", "300.00")
    assert body["tender_split"]["MPESA"] == "0.00" and body["cash_collected"]["MPESA"] == "0.00"
    products = (await api.get(f"{URL}/products", headers=a.owner)).json()
    assert products[0]["quantity"] == "1.000" and products[0]["sales_count"] == 1
    assert keep["id"]  # the kept sale is the only one counted


async def test_discounts_reduce_revenue_and_product_profit_reconciles(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    x = await make_product(api, a.owner, name="X", price="50", cost="20", stock="10")
    y = await make_product(api, a.owner, name="Y", price="50", cost="20", stock="10")
    z = await make_product(api, a.owner, name="Z", price="50", cost=None, stock="10")
    await sell(
        api,
        a.owner,
        sale_payload(
            [(x["id"], "1"), (y["id"], "1"), (z["id"], "1")],
            [("CASH", "50")],
            discount_amount="100",
        ),
    )
    body = await _summary(api, a.owner)
    assert (body["revenue"], body["discounts"]) == ("50.00", "100.00")
    assert body["cogs"] == "40.00"  # Z has no cost
    assert (body["lines_missing_cost"], body["products_missing_cost"]) == (1, 1)
    assert body["gross_profit"] == "10.00"
    products = (await api.get(f"{URL}/products", headers=a.owner, params={"sort": "profit"})).json()
    by_name = {r["name"]: r for r in products}
    # Allocation 33.34 / 33.33 / 33.33 → line revenue 16.66 / 16.67 / 16.67.
    assert (by_name["X"]["revenue"], by_name["Y"]["revenue"], by_name["Z"]["revenue"]) == (
        "16.66",
        "16.67",
        "16.67",
    )
    assert (by_name["X"]["gross_profit"], by_name["Z"]["gross_profit"]) == ("-3.34", "16.67")
    assert by_name["Z"]["lines_missing_cost"] == 1 and by_name["Z"]["cogs"] == "0.00"
    assert sum(D(r["gross_profit"]) for r in products) == D(body["gross_profit"])  # FR-I2
    assert sum(D(r["revenue"]) for r in products) == D(body["revenue"])
    assert [r["name"] for r in products] == ["Z", "Y", "X"]  # 16.67, -3.33, -3.34


async def test_cogs_uses_the_sale_time_cost_not_todays(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, price="500", cost="300", stock="10")
    await sell(api, a.owner, sale_payload([(p["id"], "2")], [("CASH", "1000")]))
    assert (
        await api.patch(
            f"{PRODUCTS_URL}/{p['id']}",
            headers=a.owner,
            json={"cost_price": "450", "name": "Renamed"},
        )
    ).status_code == 200
    body = await _summary(api, a.owner)
    assert (body["cogs"], body["gross_profit"]) == ("600.00", "400.00")
    # Archiving the product does not erase its history either.
    assert (
        await api.patch(f"{PRODUCTS_URL}/{p['id']}", headers=a.owner, json={"is_active": False})
    ).status_code == 200
    products = (await api.get(f"{URL}/products", headers=a.owner)).json()
    assert (
        products[0]["product_id"] == p["id"]
        and products[0]["is_active"] is False
        and products[0]["cogs"] == "600.00"
    )


async def test_products_sorting_and_limit(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    cheap = await make_product(api, a.owner, name="Cheap", price="10", cost="5", stock="100")
    dear = await make_product(api, a.owner, name="Dear", price="1000", cost="900", stock="100")
    await sell(api, a.owner, sale_payload([(cheap["id"], "20")], [("CASH", "200")]))
    await sell(api, a.owner, sale_payload([(dear["id"], "1")], [("CASH", "1000")]))
    await sell(api, a.owner, sale_payload([(cheap["id"], "5")], [("CASH", "50")]))
    by_qty = (await api.get(f"{URL}/products", headers=a.owner, params={"sort": "quantity"})).json()
    assert [(r["name"], r["quantity"], r["sales_count"]) for r in by_qty] == [
        ("Cheap", "25.000", 2),
        ("Dear", "1.000", 1),
    ]
    by_rev = (await api.get(f"{URL}/products", headers=a.owner, params={"sort": "revenue"})).json()
    assert [r["name"] for r in by_rev] == ["Dear", "Cheap"]
    by_profit = (
        await api.get(f"{URL}/products", headers=a.owner, params={"sort": "profit"})
    ).json()
    assert [(r["name"], r["gross_profit"]) for r in by_profit] == [
        ("Cheap", "125.00"),
        ("Dear", "100.00"),
    ]
    assert len((await api.get(f"{URL}/products", headers=a.owner, params={"limit": 1})).json()) == 1
    assert (
        await api.get(f"{URL}/products", headers=a.owner, params={"sort": "vibes"})
    ).status_code == 422


async def test_category_breakdown_includes_uncategorised(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    drinks = (
        await api.post("/api/v1/categories", headers=a.owner, json={"name": "Drinks"})
    ).json()["id"]
    soda = await make_product(
        api, a.owner, name="Soda", price="60", cost="45", stock="100", category_id=drinks
    )
    loose = await make_product(api, a.owner, name="Loose", price="10", cost=None, stock="100")
    await sell(
        api, a.owner, sale_payload([(soda["id"], "5"), (loose["id"], "3")], [("CASH", "330")])
    )
    rows = (await api.get(f"{URL}/categories", headers=a.owner)).json()
    assert [
        (
            r["name"],
            r["category_id"] is None,
            r["revenue"],
            r["cogs"],
            r["gross_profit"],
            r["lines_missing_cost"],
        )
        for r in rows
    ] == [
        ("Drinks", False, "300.00", "225.00", "75.00", 0),
        (None, True, "30.00", "0.00", "30.00", 1),
    ]
    assert rows[0]["category_id"] == drinks and rows[0]["quantity"] == "5.000"


async def test_slow_products_definition(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    never = await make_product(api, a.owner, name="Never sold", stock="4")
    recent = await make_product(api, a.owner, name="Sold today", stock="4")
    old = await make_product(api, a.owner, name="Sold long ago", stock="4")
    await make_product(api, a.owner, name="Out of stock", stock=None)  # no stock on hand
    await make_product(api, a.owner, name="Service", stock=None, tracked=False)
    await sell(api, a.owner, sale_payload([(recent["id"], "1")], [("CASH", "500")]))
    long_ago = await sell(
        api,
        a.owner,
        sale_payload(
            [(old["id"], "1")],
            [("CASH", "500")],
            sold_at=(datetime.now(UTC) - timedelta(days=6)).isoformat(),
        ),
    )
    rows = (await api.get(f"{URL}/slow-products", headers=a.owner, params={"days": 5})).json()
    assert [(r["name"], r["stock_quantity"], r["last_sold_at"] is None) for r in rows] == [
        ("Never sold", "4.000", True),
        ("Sold long ago", "3.000", False),
    ]
    assert rows[1]["last_sold_at"].startswith(long_ago["sold_at"][:16])
    assert never["id"] == rows[0]["product_id"]
    assert [
        r["name"]
        for r in (
            await api.get(f"{URL}/slow-products", headers=a.owner, params={"days": 30})
        ).json()
    ] == ["Never sold"]
    assert (
        await api.get(f"{URL}/slow-products", headers=a.owner, params={"days": 0})
    ).status_code == 422


# --- time semantics -------------------------------------------------------------------------


async def test_midnight_nairobi_boundary(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    """23:30 EAT belongs to that local day; 00:30 EAT (21:30 UTC the day before) to the next."""
    a, _ = tenants
    p = await make_product(api, a.owner, price="100", cost=None, stock="100")
    today_local = datetime.now(NAIROBI).date()
    day1 = today_local - timedelta(days=3)
    day2 = day1 + timedelta(days=1)
    late = datetime.combine(day1, datetime.min.time(), tzinfo=NAIROBI).replace(hour=23, minute=30)
    early = datetime.combine(day2, datetime.min.time(), tzinfo=NAIROBI).replace(hour=0, minute=30)
    await sell(api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "100")], sold_at=_iso(late)))
    await sell(api, a.owner, sale_payload([(p["id"], "2")], [("CASH", "200")], sold_at=_iso(early)))
    first = await _summary(
        api, a.owner, period="custom", date_from=day1.isoformat(), date_to=day1.isoformat()
    )
    second = await _summary(
        api, a.owner, period="custom", date_from=day2.isoformat(), date_to=day2.isoformat()
    )
    both = await _summary(
        api, a.owner, period="custom", date_from=day1.isoformat(), date_to=day2.isoformat()
    )
    assert (first["revenue"], second["revenue"], both["revenue"]) == ("100.00", "200.00", "300.00")
    assert (await _summary(api, a.owner, period="today"))["revenue"] == "0.00"
    series = (
        await api.get(
            f"{URL}/timeseries",
            headers=a.owner,
            params={
                "granularity": "day",
                "period": "custom",
                "date_from": day1.isoformat(),
                "date_to": day2.isoformat(),
            },
        )
    ).json()
    assert [(b["bucket_start"], b["revenue"], b["sales_count"]) for b in series["buckets"]] == [
        (day1.isoformat(), "100.00", 1),
        (day2.isoformat(), "200.00", 1),
    ]
    assert series["period"] == {
        "timezone": "Africa/Nairobi",
        "date_from": day1.isoformat(),
        "date_to": day2.isoformat(),
    }


async def test_timeseries_week_and_month_buckets_and_cash(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, price="100", cost="40", stock="100")
    c = await make_customer(api, a.owner)
    today_local = datetime.now(NAIROBI).date()
    days = [today_local - timedelta(days=n) for n in (6, 3, 0)]
    for day, qty in zip(days, (1, 2, 3), strict=True):
        at = datetime.combine(day, datetime.min.time(), tzinfo=NAIROBI).replace(hour=12)
        await sell(
            api,
            a.owner,
            sale_payload(
                [(p["id"], str(qty))],
                [("CREDIT", str(qty * 100))],
                customer_id=c["id"],
                sold_at=_iso(at) if day != today_local else None,
            ),
        )
    assert (
        await api.post(
            f"/api/v1/customers/{c['id']}/repayments",
            headers=a.owner,
            json={"amount": "150", "payment_method": "CASH"},
        )
    ).status_code == 201
    params = {
        "period": "custom",
        "date_from": days[0].isoformat(),
        "date_to": today_local.isoformat(),
    }
    daily = (
        await api.get(f"{URL}/timeseries", headers=a.owner, params={**params, "granularity": "day"})
    ).json()["buckets"]
    assert [(b["bucket_start"], b["revenue"], b["cogs"], b["gross_profit"]) for b in daily] == [
        (days[0].isoformat(), "100.00", "40.00", "60.00"),
        (days[1].isoformat(), "200.00", "80.00", "120.00"),
        (today_local.isoformat(), "300.00", "120.00", "180.00"),
    ]
    assert (
        daily[-1]["cash_collected"] == "150.00" and daily[0]["cash_collected"] == "0.00"
    )  # credit sales, one repayment today
    weekly = (
        await api.get(
            f"{URL}/timeseries", headers=a.owner, params={**params, "granularity": "week"}
        )
    ).json()["buckets"]
    assert sum(D(b["revenue"]) for b in weekly) == D("600.00")
    assert all(date.fromisoformat(b["bucket_start"]).weekday() == 0 for b in weekly)  # Mondays
    monthly = (
        await api.get(
            f"{URL}/timeseries", headers=a.owner, params={**params, "granularity": "month"}
        )
    ).json()["buckets"]
    assert sum(D(b["revenue"]) for b in monthly) == D("600.00")
    assert all(date.fromisoformat(b["bucket_start"]).day == 1 for b in monthly)


async def test_named_periods_and_invalid_ranges(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    for period in ("today", "yesterday", "this_week", "this_month"):
        assert (
            await api.get(f"{URL}/summary", headers=a.owner, params={"period": period})
        ).status_code == 200
    custom_missing = await api.get(f"{URL}/summary", headers=a.owner, params={"period": "custom"})
    assert custom_missing.status_code == 422 and error_code(custom_missing) == "INVALID_PERIOD"
    backwards = await api.get(
        f"{URL}/summary",
        headers=a.owner,
        params={"period": "custom", "date_from": "2026-09-02", "date_to": "2026-09-01"},
    )
    assert backwards.status_code == 422 and error_code(backwards) == "INVALID_PERIOD"
    too_long = await api.get(
        f"{URL}/summary",
        headers=a.owner,
        params={"period": "custom", "date_from": "2025-01-01", "date_to": "2026-12-31"},
    )
    assert too_long.status_code == 422
    assert (
        await api.get(f"{URL}/summary", headers=a.owner, params={"period": "forever"})
    ).status_code == 422


# --- authorization / isolation ------------------------------------------------------------


async def test_analytics_are_owner_only(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    for path in ("summary", "timeseries", "products", "slow-products", "categories"):
        assert (await api.get(f"{URL}/{path}")).status_code == 401
        denied = await api.get(f"{URL}/{path}", headers=a.staff)
        assert denied.status_code == HTTPStatus.FORBIDDEN and error_code(denied) == "FORBIDDEN"
    await set_business_active(db_session, uuid.UUID(a.business_id), False)
    inactive = await api.get(f"{URL}/summary", headers=a.owner)
    assert (
        inactive.status_code == HTTPStatus.FORBIDDEN and error_code(inactive) == "BUSINESS_INACTIVE"
    )


async def test_analytics_never_cross_tenants(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    pa = await make_product(api, a.owner, name="Alpha item", price="100", cost="10", stock="10")
    pb = await make_product(api, b.owner, name="Beta item", price="999", cost="1", stock="10")
    cb = await make_customer(api, b.owner, name="Beta debtor")
    await sell(api, a.owner, sale_payload([(pa["id"], "1")], [("CASH", "100")]))
    await sell(
        api, b.owner, sale_payload([(pb["id"], "2")], [("CREDIT", "1998")], customer_id=cb["id"])
    )
    a_summary = await _summary(api, a.owner)
    b_summary = await _summary(api, b.owner)
    assert (a_summary["revenue"], a_summary["receivables_outstanding"]) == ("100.00", "0.00")
    assert (b_summary["revenue"], b_summary["receivables_outstanding"]) == ("1998.00", "1998.00")
    for path in ("products", "categories"):
        a_rows = (await api.get(f"{URL}/{path}", headers=a.owner)).text
        assert "Beta" not in a_rows and pb["id"] not in a_rows
    assert [
        r["name"] for r in (await api.get(f"{URL}/slow-products", headers=a.owner)).json()
    ] == []
    assert [
        r["name"] for r in (await api.get(f"{URL}/slow-products", headers=b.owner)).json()
    ] == []
    # A client-supplied business id is simply not a parameter.
    spoofed = await api.get(
        f"{URL}/summary", headers=a.owner, params={"business_id": b.business_id}
    )
    assert spoofed.status_code == 200 and spoofed.json()["revenue"] == "100.00"
