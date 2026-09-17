"""The tools themselves: accounting semantics, bounds, read-only execution."""

import json
import uuid
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

import pytest
from app.ai.provider import ToolCall
from app.ai.service import AIService
from app.ai.tools import TOOLS, Tool
from app.core.config import Settings
from app.models import Category
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.ai_helpers import FakeProvider
from tests.db.credit_helpers import owner_context, repay
from tests.db.isolation import Tenant
from tests.db.sales_helpers import make_customer, make_product, sale_payload, sell

pytestmark = [pytest.mark.db, pytest.mark.anyio]

EXPENSES_URL = "/api/v1/expenses"


async def _run(session: AsyncSession, tenant: Tenant, name: str, **args: Any) -> dict[str, Any]:
    ctx = await owner_context(session, tenant)
    tool = TOOLS[name]
    payload = tool.input_model.model_validate(args)
    return await tool.run(session, ctx, payload, datetime.now(UTC))


async def _seed(api: AsyncClient, tenant: Tenant) -> dict[str, Any]:
    """Cash 500 + M-Pesa 300 + credit 700 sold today; 200 repaid; 100 of expenses; one
    product with no cost price."""
    sugar = await make_product(
        api, tenant.owner, name="Sugar 1kg", price="100", cost="80", stock="50"
    )
    mandazi = await make_product(
        api, tenant.owner, name="Mandazi", price="10", cost=None, stock=None, tracked=False
    )
    bread = await make_product(
        api, tenant.owner, name="Bread", price="70", cost="50", stock="2", low_stock_threshold="5"
    )
    customer = await make_customer(
        api, tenant.owner, name="Mama Njeri", phone="0712000111", credit_limit="5000"
    )
    await sell(api, tenant.owner, sale_payload([(sugar["id"], "5")], [("CASH", "500")]))
    await sell(api, tenant.owner, sale_payload([(mandazi["id"], "30")], [("MPESA", "300")]))
    await sell(
        api,
        tenant.owner,
        sale_payload([(sugar["id"], "7")], [("CREDIT", "700")], customer_id=customer["id"]),
    )
    assert (
        await repay(api, tenant.owner, customer["id"], "200", "MPESA")
    ).status_code == HTTPStatus.CREATED
    expense = await api.post(
        EXPENSES_URL,
        headers=tenant.owner,
        json={"amount": "100", "category": "Transport", "payment_method": "CASH"},
    )
    assert expense.status_code == HTTPStatus.CREATED, expense.text
    return {"sugar": sugar, "mandazi": mandazi, "bread": bread, "customer": customer}


async def test_business_summary_keeps_revenue_cash_credit_and_profit_apart(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    await _seed(api, a)
    out = await _run(
        db_session, a, "get_business_summary", period="today", date_from=None, date_to=None
    )
    assert out["currency"] == "KES"
    assert out["sales_count"] == 3
    assert out["revenue"] == "1500.00"  # accrual: the credit sale counts
    assert out["sold_by_tender"] == {"CASH": "500.00", "MPESA": "300.00", "CREDIT": "700.00"}
    # Cash collected = cash + M-Pesa tenders + the repayment; CREDIT is not cash.
    assert out["cash_collected_by_method"] == {"CASH": "500.00", "MPESA": "500.00"}
    assert out["cash_collected_total"] == "1000.00"
    assert out["receivables_outstanding_now"] == "500.00"  # 700 charged - 200 repaid
    # COGS only from lines with a cost snapshot: 12 x 80; mandazi has no cost.
    assert out["cogs"] == "960.00"
    assert out["gross_profit"] == "540.00"
    assert out["lines_missing_cost"] == 1 and out["products_missing_cost"] == 1
    assert out["expenses"] == "100.00"
    assert out["net_profit"] == "440.00"
    assert any("understated" in note for note in out["notes"])
    assert any("CREDIT is never cash" in note for note in out["notes"])


async def test_sales_products_expenses_debtors_inventory_and_search_tools(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    seeded = await _seed(api, a)

    sales = await _run(
        db_session,
        a,
        "get_sales_summary",
        period="this_week",
        date_from=None,
        date_to=None,
        top_products_limit=5,
    )
    assert sales["revenue"] == "1500.00" and sales["cash_collected_total"] == "1000.00"
    assert [p["name"] for p in sales["top_products_by_revenue"]] == ["Sugar 1kg", "Mandazi"]

    products = await _run(
        db_session,
        a,
        "get_product_performance",
        period="today",
        date_from=None,
        date_to=None,
        sort="profit",
        limit=5,
    )
    by_name = {p["name"]: p for p in products["products"]}
    assert (
        by_name["Sugar 1kg"]["gross_profit"] == "240.00"
        and by_name["Sugar 1kg"]["quantity"] == "12"
    )
    assert by_name["Mandazi"]["lines_missing_cost"] == 1 and by_name["Mandazi"]["cogs"] == "0.00"

    expenses = await _run(
        db_session, a, "get_expense_summary", period="this_month", date_from=None, date_to=None
    )
    assert expenses["total"] == "100.00" and expenses["by_category"] == [
        {"category": "TRANSPORT", "total": "100.00", "count": 1}
    ]
    assert expenses["by_payment_method"]["CASH"] == "100.00"

    debtors = await _run(db_session, a, "get_debtors", sort="balance", limit=10)
    assert [(d["name"], d["balance"]) for d in debtors["debtors"]] == [("Mama Njeri", "500.00")]
    assert debtors["debtors"][0]["customer_id"] == seeded["customer"]["id"]
    assert "0712000111" not in json.dumps(debtors)  # no phone numbers to the model

    stock = await _run(db_session, a, "get_inventory_status", limit=20)
    assert [
        (p["name"], p["stock_quantity"], p["threshold"]) for p in stock["low_stock_products"]
    ] == [("Bread", "2", "5")]

    slow = await _run(db_session, a, "get_slow_products", days=30, limit=10)
    assert [p["name"] for p in slow["products"]] == ["Bread"]  # stocked, never sold

    found = await _run(db_session, a, "search_customers", query="njeri", limit=5)
    assert found["customers"] == [
        {
            "customer_id": seeded["customer"]["id"],
            "name": "Mama Njeri",
            "balance_owed": "500.00",
            "credit_limit": "5000.00",
        }
    ]
    by_phone = await _run(db_session, a, "search_customers", query="0712000111", limit=5)
    assert [c["name"] for c in by_phone["customers"]] == ["Mama Njeri"]
    assert (await _run(db_session, a, "search_customers", query="nobody", limit=5))[
        "customers"
    ] == []


async def test_empty_periods_answer_zero_not_nothing(
    db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    out = await _run(
        db_session, a, "get_business_summary", period="last_month", date_from=None, date_to=None
    )
    assert out["sales_count"] == 0 and out["revenue"] == "0.00" and out["net_profit"] == "0.00"
    assert (await _run(db_session, a, "get_debtors", sort="age", limit=5))["debtors"] == []


async def test_tools_never_see_another_business(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    await _seed(api, b)
    for name, args in (
        ("get_business_summary", {"period": "today", "date_from": None, "date_to": None}),
        ("get_debtors", {"sort": "balance", "limit": 10}),
        ("get_inventory_status", {"limit": 10}),
        ("search_customers", {"query": "Njeri", "limit": 5}),
        ("get_expense_summary", {"period": "this_month", "date_from": None, "date_to": None}),
    ):
        out = await _run(db_session, a, name, **args)
        assert "Njeri" not in json.dumps(out) and "Sugar" not in json.dumps(out), name
    assert (
        await _run(
            db_session, a, "get_business_summary", period="today", date_from=None, date_to=None
        )
    )["revenue"] == "0.00"


async def test_tools_run_read_only_and_the_session_recovers_afterwards(
    db_session: AsyncSession, tenants: tuple[Tenant, Tenant], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, _ = tenants
    ctx = await owner_context(db_session, a)

    async def rogue(session: AsyncSession, context: Any, args: Any, now: Any) -> dict[str, Any]:
        await session.execute(
            text(
                "INSERT INTO categories (id, business_id, name) VALUES (:id, :business_id, 'Rogue')"
            ),
            {"id": uuid.uuid4(), "business_id": context.business_id},
        )
        return {"ok": True}

    monkeypatch.setitem(
        TOOLS, "get_debtors", Tool("get_debtors", "x", TOOLS["get_debtors"].input_model, rogue)
    )
    service = AIService(FakeProvider([]), Settings())
    records: list[dict[str, Any]] = []
    result = await service._run_tool(
        db_session,
        ctx,
        ToolCall("t1", "get_debtors", {"sort": "balance", "limit": 5}),
        datetime.now(UTC),
        records,
    )
    assert result["is_error"] is True
    assert json.loads(result["content"]) == {"error": "That information is not available right now"}
    rows = await db_session.scalars(select(Category).where(Category.business_id == ctx.business_id))
    assert list(rows) == []  # the write never happened
    # The read-only setting died with the savepoint: the request can still write afterwards.
    conversation = await service.create_conversation(db_session, ctx, title="after")
    assert conversation.id is not None
