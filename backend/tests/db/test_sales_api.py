"""/api/v1/sales (PRD FR-F, BR-1/3/9/14/15; DATA_MAPPING §3.9-§3.11, §6)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import Any

import pytest
from app.models import AuditLog, CreditTransaction, InventoryMovement, Payment, Sale, SaleItem
from app.services import audit as audit_service
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import error_code, set_business_active
from tests.db.credit_helpers import db_balance
from tests.db.isolation import Tenant
from tests.db.sales_helpers import (
    PRODUCTS_URL,
    SALES_URL,
    counts,
    make_customer,
    make_product,
    post_sale,
    sale_payload,
    sell,
    stock_of,
)

pytestmark = [pytest.mark.db, pytest.mark.anyio]

D = Decimal


async def _movements(session: AsyncSession, sale_id: str) -> list[InventoryMovement]:
    rows = await session.scalars(
        select(InventoryMovement)
        .where(InventoryMovement.sale_id == uuid.UUID(sale_id))
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def _credit_rows(session: AsyncSession, sale_id: str) -> list[CreditTransaction]:
    rows = await session.scalars(
        select(CreditTransaction)
        .where(CreditTransaction.sale_id == uuid.UUID(sale_id))
        .execution_options(populate_existing=True)
    )
    return list(rows)


# --- creation ------------------------------------------------------------------------------


async def test_single_item_cash_sale(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    product = await make_product(api, a.owner)
    sale = await sell(api, a.owner, sale_payload([(product["id"], "2")], [("CASH", "1000")]))
    assert sale["status"] == "COMPLETED"
    assert (sale["subtotal"], sale["discount_amount"], sale["total_amount"]) == (
        "1000.00",
        "0.00",
        "1000.00",
    )
    assert sale["customer_id"] is None and sale["created_by"] == a.owner_user_id
    assert sale["voided_at"] is None and sale["void_reason"] is None
    (item,) = sale["items"]
    assert item["product_id"] == product["id"] and item["product_name"] == "Sugar 1kg"
    assert (item["quantity"], item["unit_price"], item["default_unit_price"]) == (
        "2.000",
        "500.00",
        "500.00",
    )
    assert (item["line_total"], item["discount_allocated"]) == ("1000.00", "0.00")
    assert "unit_cost" not in item  # cost/profit is analytics, OWNER-only (§16)
    (payment,) = sale["payments"]
    assert (payment["method"], payment["amount"], payment["status"], payment["provider"]) == (
        "CASH",
        "1000.00",
        "CONFIRMED",
        "MANUAL",
    )
    assert await stock_of(db_session, product["id"]) == D("8.000")
    (movement,) = await _movements(db_session, sale["id"])
    assert movement.movement_type.value == "SALE"
    assert (movement.quantity_delta, movement.quantity_after) == (D("-2.000"), D("8.000"))
    assert movement.unit_cost == D("300.00") and movement.total_cost == D("600.00")
    row = await db_session.get(SaleItem, uuid.UUID(item["id"]))
    assert row is not None and row.unit_cost == D("300.00")  # snapshot for COGS
    assert await _credit_rows(db_session, sale["id"]) == []
    assert (await counts(db_session, a.business_id))["audit"] == 0  # creation is not audited


async def test_multi_item_sale_with_override_split_tender_and_note(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    sugar = await make_product(api, a.owner, name="Sugar", price="150", stock="20")
    oil = await make_product(api, a.owner, name="Oil", price="320.50", cost=None, stock="5")
    sale = await sell(
        api,
        a.owner,
        sale_payload(
            [(sugar["id"], "2.5"), (oil["id"], "1", "300")],
            [("CASH", "200"), ("MPESA", "475")],
            note="  Regular Friday order ",
        ),
    )
    # 2.5 x 150 = 375; 1 x 300 (override of 320.50) = 300; total 675 = 200 + 475
    assert sale["subtotal"] == "675.00" and sale["total_amount"] == "675.00"
    assert sale["note"] == "Regular Friday order"
    items = {i["product_name"]: i for i in sale["items"]}
    assert (items["Sugar"]["line_total"], items["Oil"]["line_total"]) == ("375.00", "300.00")
    assert (items["Oil"]["unit_price"], items["Oil"]["default_unit_price"]) == ("300.00", "320.50")
    assert sorted((p["method"], p["amount"]) for p in sale["payments"]) == [
        ("CASH", "200.00"),
        ("MPESA", "475.00"),
    ]
    assert await stock_of(db_session, sugar["id"]) == D("17.500")
    assert await stock_of(db_session, oil["id"]) == D("4.000")
    oil_item = await db_session.get(SaleItem, uuid.UUID(items["Oil"]["id"]))
    assert oil_item is not None and oil_item.unit_cost is None  # unknown cost stays unknown


async def test_mpesa_sale_records_the_reference_unverified(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    product = await make_product(api, a.owner)
    payload = sale_payload([(product["id"], "1")])
    payload["payments"] = [{"method": "MPESA", "amount": "500", "reference": " QGH7XYZ123 "}]
    sale = await sell(api, a.owner, payload)
    (payment,) = sale["payments"]
    assert (payment["method"], payment["reference"], payment["status"]) == (
        "MPESA",
        "QGH7XYZ123",
        "CONFIRMED",
    )


async def test_decimal_prices_and_quantities_are_exact(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, name="Tomatoes", price="0.10", stock="100")
    sale = await sell(api, a.owner, sale_payload([(p["id"], "3")], [("CASH", "0.30")]))
    assert sale["total_amount"] == "0.30"
    q = await make_product(api, a.owner, name="Rice", price="33.33", stock="100")
    sale = await sell(api, a.owner, sale_payload([(q["id"], "0.5")], [("CASH", "16.67")]))
    assert sale["items"][0]["line_total"] == "16.67"  # 16.665 half-up


async def test_same_product_on_two_lines(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, stock="3")
    sale = await sell(
        api, a.owner, sale_payload([(p["id"], "2"), (p["id"], "1", "450")], [("CASH", "1450")])
    )
    assert len(sale["items"]) == 2
    assert await stock_of(db_session, p["id"]) == D("0.000")
    assert len(await _movements(db_session, sale["id"])) == 2
    # And a fourth unit is not available.
    denied = await post_sale(api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")]))
    assert denied.status_code == HTTPStatus.CONFLICT and error_code(denied) == "INSUFFICIENT_STOCK"


# --- validation ---------------------------------------------------------------------------


async def test_payments_must_balance_and_discount_must_fit(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    before = await counts(db_session, a.business_id)
    short = await post_sale(api, a.owner, sale_payload([(p["id"], "2")], [("CASH", "999.99")]))
    assert short.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert error_code(short) == "PAYMENTS_DO_NOT_BALANCE"
    assert short.json()["error"]["details"] == {"total_amount": "1000.00", "tendered": "999.99"}
    over = await post_sale(api, a.owner, sale_payload([(p["id"], "2")], [("CASH", "1000.01")]))
    assert over.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    big_discount = await post_sale(
        api, a.owner, sale_payload([(p["id"], "2")], [("CASH", "0")], discount_amount="1000.01")
    )
    assert big_discount.status_code == HTTPStatus.UNPROCESSABLE_ENTITY  # amount>0 or discount
    exact = await post_sale(
        api, a.owner, sale_payload([(p["id"], "2")], [("CASH", "1")], discount_amount="1000.01")
    )
    assert exact.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert error_code(exact) == "DISCOUNT_EXCEEDS_SUBTOTAL"
    assert await counts(db_session, a.business_id) == before
    assert await stock_of(db_session, p["id"]) == D("10.000")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(lines=[]),
        lambda p: p.update(payments=[]),
        lambda p: p["lines"][0].update(quantity="0"),
        lambda p: p["lines"][0].update(quantity="-1"),
        lambda p: p["lines"][0].update(quantity="1.2345"),
        lambda p: p["lines"][0].update(unit_price="-1"),
        lambda p: p["lines"][0].update(product_id="nope"),
        lambda p: p["payments"][0].update(method="CARD"),
        lambda p: p["payments"][0].update(amount="0"),
        lambda p: p.update(discount_amount="-1"),
        lambda p: p.update(total_amount="1"),
        lambda p: p.update(business_id=str(uuid.uuid4())),
        lambda p: p.update(sold_at="2026-09-16T10:00:00"),  # naive
        lambda p: p.update(payments=[{"method": "CREDIT", "amount": "500"}]),  # no customer
    ],
)
async def test_malformed_sales_are_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], mutate: Any
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    payload = sale_payload([(p["id"], "1")], [("CASH", "500")])
    mutate(payload)
    response = await post_sale(api, a.owner, payload)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    assert error_code(response) == "VALIDATION_ERROR"


async def test_missing_idempotency_key_is_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    response = await api.post(
        SALES_URL, headers=a.owner, json=sale_payload([(p["id"], "1")], [("CASH", "500")])
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


# --- inventory ---------------------------------------------------------------------------


async def test_untracked_product_sells_without_stock_or_movement(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    haircut = await make_product(
        api,
        a.owner,
        name="Haircut",
        price="300",
        cost="50",
        stock=None,
        tracked=False,
        unit="service",
    )
    sale = await sell(api, a.owner, sale_payload([(haircut["id"], "2")], [("CASH", "600")]))
    assert sale["total_amount"] == "600.00"
    assert await _movements(db_session, sale["id"]) == []
    assert await stock_of(db_session, haircut["id"]) == D("0.000")
    item = await db_session.get(SaleItem, uuid.UUID(sale["items"][0]["id"]))
    assert item is not None and item.unit_cost == D("50.00")  # still snapshots cost (FR-E1)


async def test_insufficient_stock_rejects_the_whole_sale(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    plenty = await make_product(api, a.owner, name="Plenty", stock="100")
    scarce = await make_product(api, a.owner, name="Scarce", stock="1")
    before = await counts(db_session, a.business_id)
    response = await post_sale(
        api, a.owner, sale_payload([(plenty["id"], "5"), (scarce["id"], "2")], [("CASH", "3500")])
    )
    assert response.status_code == HTTPStatus.CONFLICT
    assert error_code(response) == "INSUFFICIENT_STOCK"
    assert await counts(db_session, a.business_id) == before  # nothing partial
    assert await stock_of(db_session, plenty["id"]) == D("100.000")
    assert await stock_of(db_session, scarce["id"]) == D("1.000")


async def test_archived_product_cannot_be_sold_but_history_stays(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    sale = await sell(api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")]))
    assert (
        await api.patch(f"{PRODUCTS_URL}/{p['id']}", headers=a.owner, json={"is_active": False})
    ).status_code == 200
    denied = await post_sale(api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")]))
    assert denied.status_code == HTTPStatus.CONFLICT and error_code(denied) == "PRODUCT_ARCHIVED"
    old = await api.get(f"{SALES_URL}/{sale['id']}", headers=a.owner)
    assert (
        old.status_code == HTTPStatus.OK and old.json()["items"][0]["product_name"] == "Sugar 1kg"
    )


async def test_repricing_never_changes_a_recorded_sale(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    sale = await sell(api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")]))
    patched = await api.patch(
        f"{PRODUCTS_URL}/{p['id']}",
        headers=a.owner,
        json={"selling_price": "999", "cost_price": "1", "name": "Renamed"},
    )
    assert patched.status_code == HTTPStatus.OK
    again = (await api.get(f"{SALES_URL}/{sale['id']}", headers=a.owner)).json()
    assert again["items"][0]["unit_price"] == "500.00"
    assert again["items"][0]["default_unit_price"] == "500.00"
    assert again["items"][0]["product_name"] == "Sugar 1kg"
    assert again["total_amount"] == "1000.00" or again["total_amount"] == "500.00"
    item = await db_session.get(SaleItem, uuid.UUID(again["items"][0]["id"]))
    assert item is not None
    await db_session.refresh(item)
    assert item.unit_cost == D("300.00")
    (movement,) = await _movements(db_session, sale["id"])
    assert movement.unit_cost == D("300.00")


# --- discounts -----------------------------------------------------------------------


async def test_discount_is_allocated_by_largest_remainder_and_sums_exactly(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    x = await make_product(api, a.owner, name="X", price="50", stock="10")
    y = await make_product(api, a.owner, name="Y", price="50", stock="10")
    z = await make_product(api, a.owner, name="Z", price="50", stock="10")
    sale = await sell(
        api,
        a.owner,
        sale_payload(
            [(x["id"], "1"), (y["id"], "1"), (z["id"], "1")],
            [("CASH", "50")],
            discount_amount="100",
        ),
    )
    assert (sale["subtotal"], sale["discount_amount"], sale["total_amount"]) == (
        "150.00",
        "100.00",
        "50.00",
    )
    allocations = [i["discount_allocated"] for i in sale["items"]]
    assert allocations == ["33.34", "33.33", "33.33"]
    assert sum(D(v) for v in allocations) == D("100.00")
    row = await db_session.get(Sale, uuid.UUID(sale["id"]))
    assert row is not None and row.total_amount == row.subtotal - row.discount_amount


async def test_uneven_discount_allocation(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    p1 = await make_product(api, a.owner, name="A", price="12.34", stock="10")
    p2 = await make_product(api, a.owner, name="B", price="56.78", stock="10")
    p3 = await make_product(api, a.owner, name="C", price="9.10", stock="10")
    sale = await sell(
        api,
        a.owner,
        sale_payload(
            [(p1["id"], "1"), (p2["id"], "1"), (p3["id"], "1")],
            [("CASH", "68.22")],
            discount_amount="10",
        ),
    )
    assert [i["discount_allocated"] for i in sale["items"]] == ["1.58", "7.26", "1.16"]
    assert sale["total_amount"] == "68.22"


async def test_full_discount_is_allowed_with_matching_tender(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    """A 100% discount leaves nothing to tender, and payment lines must be > 0: not a sale."""
    a, _ = tenants
    p = await make_product(api, a.owner)
    response = await post_sale(
        api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "0.01")], discount_amount="500")
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert error_code(response) == "PAYMENTS_DO_NOT_BALANCE"


# --- credit -----------------------------------------------------------------------------


async def test_credit_sale_charges_the_customer_and_is_not_cash(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    c = await make_customer(api, a.owner, credit_limit="5000")
    sale = await sell(
        api, a.owner, sale_payload([(p["id"], "3")], [("CREDIT", "1500")], customer_id=c["id"])
    )
    assert sale["customer_id"] == c["id"]
    (payment,) = sale["payments"]
    assert payment["method"] == "CREDIT" and payment["amount"] == "1500.00"
    assert await db_balance(db_session, c["id"]) == (D("1500.00"), D("1500.00"))
    (entry,) = await _credit_rows(db_session, sale["id"])
    assert entry.entry_type.value == "CHARGE" and entry.amount == D("1500.00")
    assert entry.balance_after == D("1500.00")
    assert entry.payment_id == uuid.UUID(payment["id"]) and entry.customer_id == uuid.UUID(c["id"])
    assert entry.created_by == uuid.UUID(a.owner_user_id)
    assert await stock_of(db_session, p["id"]) == D("7.000")
    ledger = (await api.get(f"/api/v1/customers/{c['id']}/ledger", headers=a.owner)).json()
    assert ledger["entries"][0]["sale_id"] == sale["id"]
    # Revenue is the sale total; cash collected from this sale is zero (BR-15).
    payments = (
        await db_session.scalars(select(Payment).where(Payment.sale_id == uuid.UUID(sale["id"])))
    ).all()
    assert sum((x.amount for x in payments if x.method.value != "CREDIT"), D("0")) == D("0")


async def test_part_cash_part_credit(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    c = await make_customer(api, a.owner)
    sale = await sell(
        api,
        a.owner,
        sale_payload([(p["id"], "2")], [("CASH", "300"), ("CREDIT", "700")], customer_id=c["id"]),
    )
    assert await db_balance(db_session, c["id"]) == (D("700.00"), D("700.00"))
    (entry,) = await _credit_rows(db_session, sale["id"])
    assert entry.amount == D("700.00")


async def test_cash_sale_with_customer_does_not_touch_the_balance(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    c = await make_customer(api, a.owner)
    sale = await sell(
        api, a.owner, sale_payload([(p["id"], "1")], [("MPESA", "500")], customer_id=c["id"])
    )
    assert sale["customer_id"] == c["id"]
    assert await db_balance(db_session, c["id"]) == (D("0.00"), D("0.00"))
    assert await _credit_rows(db_session, sale["id"]) == []


async def test_credit_limit_blocks_staff_and_warns_owner(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner, stock="100")
    c = await make_customer(api, a.owner, credit_limit="1000")
    ok = await post_sale(
        api, a.staff, sale_payload([(p["id"], "2")], [("CREDIT", "1000")], customer_id=c["id"])
    )
    assert ok.status_code == HTTPStatus.CREATED  # exactly at the limit
    before = await counts(db_session, a.business_id)
    staff_over = await post_sale(
        api, a.staff, sale_payload([(p["id"], "1")], [("CREDIT", "500")], customer_id=c["id"])
    )
    assert staff_over.status_code == HTTPStatus.CONFLICT
    assert error_code(staff_over) == "CREDIT_LIMIT_EXCEEDED"
    assert staff_over.json()["error"]["details"]["owner_may_override"] is False
    owner_warned = await post_sale(
        api, a.owner, sale_payload([(p["id"], "1")], [("CREDIT", "500")], customer_id=c["id"])
    )
    assert owner_warned.status_code == HTTPStatus.CONFLICT
    assert owner_warned.json()["error"]["details"]["owner_may_override"] is True
    assert await counts(db_session, a.business_id) == before
    assert await stock_of(db_session, p["id"]) == D("98.000")
    # STAFF cannot use the override; OWNER can, and it is audited.
    staff_forced = await post_sale(
        api,
        a.staff,
        sale_payload(
            [(p["id"], "1")], [("CREDIT", "500")], customer_id=c["id"], credit_limit_override=True
        ),
    )
    assert staff_forced.status_code == HTTPStatus.CONFLICT
    forced = await post_sale(
        api,
        a.owner,
        sale_payload(
            [(p["id"], "1")], [("CREDIT", "500")], customer_id=c["id"], credit_limit_override=True
        ),
    )
    assert forced.status_code == HTTPStatus.CREATED, forced.text
    assert await db_balance(db_session, c["id"]) == (D("1500.00"), D("1500.00"))
    rows = (
        await db_session.scalars(
            select(AuditLog).where(AuditLog.action == "sale.credit_limit_override")
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].entity_id == uuid.UUID(forced.json()["id"])
    assert rows[0].after == {
        "customer_id": c["id"],
        "credit_amount": "500.00",
        "balance_before": "1000.00",
        "credit_limit": "1000.00",
        "projected_balance": "1500.00",
    }


async def test_no_credit_customer_and_archived_customer(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    from app.models import Customer

    a, _ = tenants
    p = await make_product(api, a.owner)
    cash_only = await make_customer(api, a.owner, name="Cash only", credit_limit="0")
    denied = await post_sale(
        api,
        a.owner,
        sale_payload([(p["id"], "1")], [("CREDIT", "500")], customer_id=cash_only["id"]),
    )
    assert (
        denied.status_code == HTTPStatus.CONFLICT and error_code(denied) == "CREDIT_LIMIT_EXCEEDED"
    )
    archived = await make_customer(api, a.owner, name="Gone")
    row = await db_session.get(Customer, uuid.UUID(archived["id"]))
    assert row is not None
    row.is_active = False
    await db_session.flush()
    gone = await post_sale(
        api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")], customer_id=archived["id"])
    )
    assert gone.status_code == HTTPStatus.CONFLICT and error_code(gone) == "CUSTOMER_ARCHIVED"


# --- idempotency ---------------------------------------------------------------------


async def test_same_key_same_payload_returns_the_original_sale(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    c = await make_customer(api, a.owner)
    key = str(uuid.uuid4())
    payload = sale_payload([(p["id"], "2")], [("CREDIT", "1000")], customer_id=c["id"])
    first = await post_sale(api, a.owner, payload, key)
    assert first.status_code == HTTPStatus.CREATED
    before = await counts(db_session, a.business_id)
    retry = await post_sale(api, a.owner, payload, key)
    assert retry.status_code == HTTPStatus.OK
    assert retry.json() == first.json()
    assert await counts(db_session, a.business_id) == before
    assert await stock_of(db_session, p["id"]) == D("8.000")
    assert await db_balance(db_session, c["id"]) == (D("1000.00"), D("1000.00"))


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["lines"][0].update(quantity="3"),
        lambda p: p["lines"][0].update(unit_price="499"),
        lambda p: p.update(discount_amount="1"),
        lambda p: p["payments"][0].update(method="MPESA"),
        lambda p: p["payments"][0].update(reference="OTHER"),
        lambda p: p.update(note="different"),
        lambda p: p.update(customer_id=None),
    ],
)
async def test_same_key_different_payload_is_409_and_changes_nothing(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant], change: Any
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    c = await make_customer(api, a.owner)
    key = str(uuid.uuid4())
    payload = sale_payload([(p["id"], "2")], [("CASH", "1000")], customer_id=c["id"])
    first = await post_sale(api, a.owner, payload, key)
    assert first.status_code == HTTPStatus.CREATED
    before = await counts(db_session, a.business_id)
    change(payload)
    if (
        "unit_price" in payload["lines"][0]
        or "discount_amount" in payload
        or payload["lines"][0]["quantity"] != "2"
    ):
        payload["payments"][0]["amount"] = "1"  # keep it well-formed; the hash is what matters
    conflict = await post_sale(api, a.owner, payload, key)
    assert conflict.status_code == HTTPStatus.CONFLICT, conflict.text
    assert error_code(conflict) == "IDEMPOTENCY_CONFLICT"
    assert await counts(db_session, a.business_id) == before
    assert (
        await api.get(f"{SALES_URL}/{first.json()['id']}", headers=a.owner)
    ).json() == first.json()


async def test_idempotency_keys_are_per_business(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    pa = await make_product(api, a.owner)
    pb = await make_product(api, b.owner)
    key = str(uuid.uuid4())
    assert (
        await post_sale(api, a.owner, sale_payload([(pa["id"], "1")], [("CASH", "500")]), key)
    ).status_code == 201
    assert (
        await post_sale(api, b.owner, sale_payload([(pb["id"], "1")], [("CASH", "500")]), key)
    ).status_code == 201


# --- read / list ------------------------------------------------------------------------


async def test_owner_lists_all_sales_newest_first_with_filters(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner, stock="100")
    c = await make_customer(api, a.owner)
    s1 = await sell(api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")]))
    s2 = await sell(
        api, a.staff, sale_payload([(p["id"], "1")], [("CASH", "500")], customer_id=c["id"])
    )
    pb = await make_product(api, b.owner)
    foreign = await sell(api, b.owner, sale_payload([(pb["id"], "1")], [("CASH", "500")]))

    listed = await api.get(SALES_URL, headers=a.owner)
    assert listed.status_code == HTTPStatus.OK
    assert [s["id"] for s in listed.json()] == [s2["id"], s1["id"]]
    assert foreign["id"] not in listed.text
    by_customer = (
        await api.get(SALES_URL, headers=a.owner, params={"customer_id": c["id"]})
    ).json()
    assert [s["id"] for s in by_customer] == [s2["id"]]
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert (await api.get(SALES_URL, headers=a.owner, params={"date_from": tomorrow})).json() == []
    assert len((await api.get(SALES_URL, headers=a.owner, params={"limit": 1})).json()) == 1
    assert (await api.get(SALES_URL, headers=a.owner, params={"limit": 0})).status_code == 422


async def test_staff_see_only_their_own_sales_from_today(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner, stock="100")
    owner_sale = await sell(api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")]))
    staff_sale = await sell(api, a.staff, sale_payload([(p["id"], "1")], [("CASH", "500")]))
    listed = (await api.get(SALES_URL, headers=a.staff)).json()
    assert [s["id"] for s in listed] == [staff_sale["id"]]
    assert (await api.get(f"{SALES_URL}/{staff_sale['id']}", headers=a.staff)).status_code == 200
    assert (await api.get(f"{SALES_URL}/{owner_sale['id']}", headers=a.staff)).status_code == 404
    # A sale of theirs from yesterday is out of view too.
    row = await db_session.get(Sale, uuid.UUID(staff_sale["id"]))
    assert row is not None
    row.sold_at = datetime.now(UTC) - timedelta(days=2)
    await db_session.flush()
    assert (await api.get(SALES_URL, headers=a.staff)).json() == []
    assert (await api.get(f"{SALES_URL}/{staff_sale['id']}", headers=a.staff)).status_code == 404
    assert (await api.get(f"{SALES_URL}/{staff_sale['id']}", headers=a.owner)).status_code == 200


async def test_backdating_is_owner_only_and_windowed(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner, stock="100")
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    staff = await post_sale(
        api, a.staff, sale_payload([(p["id"], "1")], [("CASH", "500")], sold_at=yesterday)
    )
    assert staff.status_code == HTTPStatus.FORBIDDEN
    owner = await post_sale(
        api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")], sold_at=yesterday)
    )
    assert owner.status_code == HTTPStatus.CREATED
    assert owner.json()["sold_at"].startswith(yesterday[:13])
    too_old = (datetime.now(UTC) - timedelta(days=8)).isoformat()  # default window 7 days
    old = await post_sale(
        api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")], sold_at=too_old)
    )
    assert (
        old.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        and error_code(old) == "SALE_BACKDATE_WINDOW"
    )
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    ahead = await post_sale(
        api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")], sold_at=future)
    )
    assert (
        ahead.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        and error_code(ahead) == "SALE_IN_FUTURE"
    )


# --- void ----------------------------------------------------------------------------------


async def test_void_restores_stock_reverses_credit_and_audits(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    c = await make_customer(api, a.owner)
    sale = await sell(
        api,
        a.owner,
        sale_payload([(p["id"], "3")], [("CASH", "500"), ("CREDIT", "1000")], customer_id=c["id"]),
    )
    # Archive the product and repay part of the debt before voiding (BR-8, DATA_MAPPING §3.7).
    assert (
        await api.patch(f"{PRODUCTS_URL}/{p['id']}", headers=a.owner, json={"is_active": False})
    ).status_code == 200
    assert (
        await api.post(
            f"/api/v1/customers/{c['id']}/repayments",
            headers=a.owner,
            json={"amount": "400", "payment_method": "CASH"},
        )
    ).status_code == 201
    assert await db_balance(db_session, c["id"]) == (D("600.00"), D("600.00"))

    voided = await api.post(
        f"{SALES_URL}/{sale['id']}/void", headers=a.owner, json={"reason": "wrong customer"}
    )
    assert voided.status_code == HTTPStatus.OK, voided.text
    body = voided.json()
    assert body["status"] == "VOIDED" and body["void_reason"] == "wrong customer"
    assert body["voided_by"] == a.owner_user_id and body["voided_at"] is not None
    assert body["items"] and body["payments"]  # history intact
    assert await stock_of(db_session, p["id"]) == D("10.000")
    movements = await _movements(db_session, sale["id"])
    assert sorted(m.movement_type.value for m in movements) == ["SALE", "SALE_REVERSAL"]
    reversal = next(m for m in movements if m.movement_type.value == "SALE_REVERSAL")
    assert (reversal.quantity_delta, reversal.quantity_after, reversal.unit_cost) == (
        D("3.000"),
        D("10.000"),
        D("300.00"),
    )
    # Full charge reversed although 400 was repaid: balance goes to -400 (credit in favour).
    assert await db_balance(db_session, c["id"]) == (D("-400.00"), D("-400.00"))
    entries = await _credit_rows(db_session, sale["id"])
    assert sorted((e.entry_type.value, e.amount) for e in entries) == [
        ("CHARGE", D("1000.00")),
        ("REVERSAL", D("-1000.00")),
    ]
    audit = (await db_session.scalars(select(AuditLog).where(AuditLog.action == "sale.void"))).all()
    assert len(audit) == 1 and audit[0].entity_id == uuid.UUID(sale["id"])
    assert audit[0].after == {
        "status": "VOIDED",
        "reason": "wrong customer",
        "total_amount": "1500.00",
        "credit_reversed": "1000.00",
    }

    again = await api.post(
        f"{SALES_URL}/{sale['id']}/void", headers=a.owner, json={"reason": "twice"}
    )
    assert again.status_code == HTTPStatus.CONFLICT and error_code(again) == "SALE_ALREADY_VOIDED"
    assert await stock_of(db_session, p["id"]) == D("10.000")


async def test_void_is_owner_only_and_needs_a_reason(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner)
    sale = await sell(api, a.staff, sale_payload([(p["id"], "1")], [("CASH", "500")]))
    denied = await api.post(
        f"{SALES_URL}/{sale['id']}/void", headers=a.staff, json={"reason": "oops"}
    )
    assert denied.status_code == HTTPStatus.FORBIDDEN
    assert (
        await api.post(f"{SALES_URL}/{sale['id']}/void", headers=a.owner, json={"reason": ""})
    ).status_code == 422
    assert (
        await api.post(f"{SALES_URL}/{sale['id']}/void", headers=a.owner, json={})
    ).status_code == 422
    assert (await api.get(f"{SALES_URL}/{sale['id']}", headers=a.owner)).json()[
        "status"
    ] == "COMPLETED"


# --- atomicity ------------------------------------------------------------------------------


async def test_failure_after_the_ledger_writes_rolls_back_the_whole_sale(
    api: AsyncClient,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    c = await make_customer(api, a.owner, credit_limit="100")
    before = await counts(db_session, a.business_id)
    real_record = audit_service.record

    async def record_then_fail(*args: object, **kwargs: object) -> object:
        await real_record(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("simulated failure after audit")

    # Override path: sale, items, payment, movement, CHARGE and audit are all written first.
    monkeypatch.setattr("app.services.sales.audit.record", record_then_fail)
    response = await post_sale(
        api,
        a.owner,
        sale_payload(
            [(p["id"], "2")], [("CREDIT", "1000")], customer_id=c["id"], credit_limit_override=True
        ),
    )
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert "simulated" not in response.text
    assert await counts(db_session, a.business_id) == before
    assert await stock_of(db_session, p["id"]) == D("10.000")
    assert await db_balance(db_session, c["id"]) == (D("0.00"), D("0.00"))


async def test_failure_in_the_credit_step_rolls_back_stock(
    api: AsyncClient,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    c = await make_customer(api, a.owner)
    before = await counts(db_session, a.business_id)

    async def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("ledger down")

    monkeypatch.setattr("app.services.sales.credit.post_entry", boom)
    response = await post_sale(
        api, a.owner, sale_payload([(p["id"], "2")], [("CREDIT", "1000")], customer_id=c["id"])
    )
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert await counts(db_session, a.business_id) == before
    assert await stock_of(db_session, p["id"]) == D("10.000")


# --- authorization / isolation --------------------------------------------------------------


async def test_unauthenticated_and_inactive_business(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner)
    payload = sale_payload([(p["id"], "1")], [("CASH", "500")])
    assert (await api.get(SALES_URL)).status_code == HTTPStatus.UNAUTHORIZED
    assert (
        await api.post(SALES_URL, headers={"Idempotency-Key": str(uuid.uuid4())}, json=payload)
    ).status_code == 401
    await set_business_active(db_session, uuid.UUID(a.business_id), False)
    response = await post_sale(api, a.owner, payload)
    assert (
        response.status_code == HTTPStatus.FORBIDDEN and error_code(response) == "BUSINESS_INACTIVE"
    )
    assert (await api.get(SALES_URL, headers=a.owner)).status_code == HTTPStatus.FORBIDDEN


async def test_cross_tenant_product_and_customer_create_nothing(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    product_a = await make_product(api, a.owner)
    customer_a = await make_customer(api, a.owner, name="Alpha Customer")
    product_b = await make_product(api, b.owner)
    before_a, before_b = (
        await counts(db_session, a.business_id),
        await counts(db_session, b.business_id),
    )

    with_a_product = await post_sale(
        api, b.owner, sale_payload([(product_a["id"], "1")], [("CASH", "500")])
    )
    assert (
        with_a_product.status_code == HTTPStatus.NOT_FOUND
        and error_code(with_a_product) == "NOT_FOUND"
    )
    with_a_customer = await post_sale(
        api,
        b.owner,
        sale_payload([(product_b["id"], "1")], [("CREDIT", "500")], customer_id=customer_a["id"]),
    )
    assert with_a_customer.status_code == HTTPStatus.NOT_FOUND
    assert "Alpha" not in with_a_customer.text and "Sugar" not in with_a_product.text
    mixed = await post_sale(
        api,
        b.owner,
        sale_payload([(product_b["id"], "1"), (product_a["id"], "1")], [("CASH", "1000")]),
    )
    assert mixed.status_code == HTTPStatus.NOT_FOUND

    assert await counts(db_session, a.business_id) == before_a
    assert await counts(db_session, b.business_id) == before_b
    assert await stock_of(db_session, product_a["id"]) == D("10.000")
    assert await stock_of(db_session, product_b["id"]) == D("10.000")
    assert await db_balance(db_session, customer_a["id"]) == (D("0.00"), D("0.00"))

    # B cannot read or void A's sale either.
    sale_a = await sell(api, a.owner, sale_payload([(product_a["id"], "1")], [("CASH", "500")]))
    assert (await api.get(f"{SALES_URL}/{sale_a['id']}", headers=b.owner)).status_code == 404
    assert (
        await api.post(f"{SALES_URL}/{sale_a['id']}/void", headers=b.owner, json={"reason": "x"})
    ).status_code == 404
    assert (await api.get(f"{SALES_URL}/{sale_a['id']}", headers=a.owner)).json()[
        "status"
    ] == "COMPLETED"
