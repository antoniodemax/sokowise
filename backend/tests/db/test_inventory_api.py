"""/api/v1/inventory (PRD FR-E, BR-4, BR-6, BR-11, §16; DATA_MAPPING §3.7)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import Any

import pytest
from app.models import AuditLog, InventoryMovement, Product
from app.services import audit as audit_service
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import error_code, set_business_active
from tests.db.isolation import Tenant
from tests.db.sales_helpers import PRODUCTS_URL, make_product, sale_payload, sell, stock_of

pytestmark = [pytest.mark.db, pytest.mark.anyio]

D = Decimal
URL = "/api/v1/inventory"
BUSINESS_URL = "/api/v1/business"


async def restock(
    api: AsyncClient,
    headers: dict[str, str],
    product_id: str,
    qty: str,
    cost: str = "250",
    **extra: Any,
) -> Any:
    return await api.post(
        f"{URL}/restock",
        headers=headers,
        json={"product_id": product_id, "quantity": qty, "unit_cost": cost, **extra},
    )


async def adjust(
    api: AsyncClient,
    headers: dict[str, str],
    product_id: str,
    delta: str,
    reason: str = "stock-take",
    **extra: Any,
) -> Any:
    return await api.post(
        f"{URL}/adjust",
        headers=headers,
        json={"product_id": product_id, "quantity_delta": delta, "reason": reason, **extra},
    )


async def _audits(session: AsyncSession, business_id: str, action: str) -> list[AuditLog]:
    rows = await session.scalars(
        select(AuditLog)
        .where(AuditLog.business_id == uuid.UUID(business_id), AuditLog.action == action)
        .execution_options(populate_existing=True)
    )
    return list(rows)


# --- restock ---------------------------------------------------------------------------


async def test_owner_restocks_a_tracked_product(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, stock="10", cost="300")
    response = await restock(
        api, a.owner, p["id"], "24.5", "280", supplier_name=" Bidco ", reason="weekly delivery"
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    body = response.json()
    assert body["movement_type"] == "RESTOCK"
    assert (body["quantity_delta"], body["quantity_after"]) == ("24.500", "34.500")
    assert (body["unit_cost"], body["total_cost"]) == ("280.00", "6860.00")
    assert body["supplier_name"] == "Bidco" and body["reason"] == "weekly delivery"
    assert body["created_by"] == a.owner_user_id and body["sale_id"] is None
    assert await stock_of(db_session, p["id"]) == D("34.500")
    product = await db_session.get(Product, uuid.UUID(p["id"]))
    assert product is not None and product.cost_price == D("300.00")  # unchanged by default
    rows = await _audits(db_session, a.business_id, "inventory.restock")
    assert len(rows) == 1 and rows[0].entity_id == uuid.UUID(p["id"])
    assert rows[0].after == {
        "movement_id": body["id"],
        "quantity_delta": "24.500",
        "quantity_after": "34.500",
        "unit_cost": "280.00",
    }


async def test_restock_may_update_the_product_cost(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, stock="10", cost="300")
    assert (
        await restock(api, a.owner, p["id"], "5", "320", update_cost_price=True)
    ).status_code == 201
    product = await db_session.get(Product, uuid.UUID(p["id"]))
    assert product is not None
    await db_session.refresh(product)
    assert product.cost_price == D("320.00")
    rows = await _audits(db_session, a.business_id, "inventory.restock")
    assert rows[0].after is not None and rows[0].after["cost_price"] == {
        "before": "300.00",
        "after": "320.00",
    }
    # Restocks are stock in, not expenses (BR-6): nothing lands in expenses.
    from app.models import Expense

    assert (await db_session.scalars(select(Expense))).all() == []


async def test_staff_restock_follows_the_business_setting(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner, stock="10")
    denied = await restock(api, a.staff, p["id"], "1")
    assert denied.status_code == HTTPStatus.FORBIDDEN and error_code(denied) == "FORBIDDEN"
    assert (
        await api.patch(
            BUSINESS_URL, headers=a.owner, json={"settings": {"staff_can_restock": True}}
        )
    ).status_code == 200
    allowed = await restock(api, a.staff, p["id"], "1")
    assert (
        allowed.status_code == HTTPStatus.CREATED
        and allowed.json()["created_by"] == a.staff_user_id
    )
    # The setting takes effect immediately in both directions.
    assert (
        await api.patch(
            BUSINESS_URL, headers=a.owner, json={"settings": {"staff_can_restock": False}}
        )
    ).status_code == 200
    assert (await restock(api, a.staff, p["id"], "1")).status_code == HTTPStatus.FORBIDDEN


async def test_restock_rejects_untracked_archived_and_foreign_products(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    service = await make_product(api, a.owner, name="Haircut", stock=None, tracked=False)
    untracked = await restock(api, a.owner, service["id"], "1")
    assert (
        untracked.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        and error_code(untracked) == "PRODUCT_UNTRACKED"
    )
    archived = await make_product(api, a.owner, name="Old", stock="1")
    await api.patch(f"{PRODUCTS_URL}/{archived['id']}", headers=a.owner, json={"is_active": False})
    gone = await restock(api, a.owner, archived["id"], "1")
    assert gone.status_code == HTTPStatus.CONFLICT and error_code(gone) == "PRODUCT_ARCHIVED"
    foreign = await make_product(api, b.owner, stock="1")
    other = await restock(api, a.owner, foreign["id"], "1")
    assert other.status_code == HTTPStatus.NOT_FOUND and error_code(other) == "NOT_FOUND"
    assert await stock_of(db_session, foreign["id"]) == D("1.000")
    assert await _audits(db_session, a.business_id, "inventory.restock") == []


@pytest.mark.parametrize(
    "body",
    [
        {"quantity": "0", "unit_cost": "1"},
        {"quantity": "-1", "unit_cost": "1"},
        {"quantity": "1.2345", "unit_cost": "1"},
        {"quantity": "1"},  # unit_cost required for RESTOCK
        {"quantity": "1", "unit_cost": "-1"},
        {"quantity": "1", "unit_cost": "1.005"},
        {"quantity": "1", "unit_cost": "1", "supplier_name": "x" * 121},
        {"quantity": "1", "unit_cost": "1", "quantity_after": "99"},
    ],
)
async def test_invalid_restock_payloads_are_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], body: dict[str, str]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, stock="1")
    response = await api.post(
        f"{URL}/restock", headers=a.owner, json={"product_id": p["id"], **body}
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, body


# --- adjust -------------------------------------------------------------------------------


async def test_owner_adjusts_up_and_down_with_reason_and_audit(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, stock="10")
    down = await adjust(api, a.owner, p["id"], "-3.5", reason="breakage")
    assert down.status_code == HTTPStatus.CREATED, down.text
    assert (
        down.json()["movement_type"],
        down.json()["quantity_delta"],
        down.json()["quantity_after"],
    ) == ("ADJUSTMENT", "-3.500", "6.500")
    assert down.json()["reason"] == "breakage" and down.json()["unit_cost"] is None
    up = await adjust(api, a.owner, p["id"], "1", reason="found in store")
    assert up.status_code == HTTPStatus.CREATED and up.json()["quantity_after"] == "7.500"
    assert await stock_of(db_session, p["id"]) == D("7.500")
    rows = await _audits(db_session, a.business_id, "inventory.adjust")
    assert {(r.before or {}).get("stock_quantity") for r in rows} == {"10.000", "6.500"}
    assert {(r.after or {}).get("reason") for r in rows} == {"breakage", "found in store"}


async def test_adjustment_cannot_take_stock_below_zero(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, stock="2")
    response = await adjust(api, a.owner, p["id"], "-2.001")
    assert (
        response.status_code == HTTPStatus.CONFLICT and error_code(response) == "INSUFFICIENT_STOCK"
    )
    assert (await adjust(api, a.owner, p["id"], "-2")).status_code == HTTPStatus.CREATED
    assert await stock_of(db_session, p["id"]) == D("0.000")
    assert (await adjust(api, a.owner, p["id"], "-0.001")).status_code == HTTPStatus.CONFLICT
    assert len(await _audits(db_session, a.business_id, "inventory.adjust")) == 1


async def test_adjustment_is_owner_only_and_needs_a_reason(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner, stock="10")
    assert (await adjust(api, a.staff, p["id"], "1")).status_code == HTTPStatus.FORBIDDEN
    for body in (
        {"quantity_delta": "1"},
        {"quantity_delta": "1", "reason": ""},
        {"quantity_delta": "0", "reason": "r"},
        {"quantity_delta": "1.2345", "reason": "r"},
    ):
        response = await api.post(
            f"{URL}/adjust", headers=a.owner, json={"product_id": p["id"], **body}
        )
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, body


async def test_adjustment_rejects_untracked_archived_and_foreign(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    service = await make_product(api, a.owner, name="Haircut", stock=None, tracked=False)
    assert error_code(await adjust(api, a.owner, service["id"], "1")) == "PRODUCT_UNTRACKED"
    archived = await make_product(api, a.owner, name="Old", stock="1")
    await api.patch(f"{PRODUCTS_URL}/{archived['id']}", headers=a.owner, json={"is_active": False})
    assert error_code(await adjust(api, a.owner, archived["id"], "1")) == "PRODUCT_ARCHIVED"
    foreign = await make_product(api, b.owner, stock="1")
    assert (await adjust(api, a.owner, foreign["id"], "1")).status_code == HTTPStatus.NOT_FOUND


# --- initial ---------------------------------------------------------------------------


async def test_initial_stock_only_for_products_without_movements(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    empty = await make_product(api, a.owner, stock=None)
    assert (
        await api.post(
            f"{URL}/initial",
            headers=a.staff,
            json={"product_id": empty["id"], "quantity": "5", "unit_cost": "1"},
        )
    ).status_code == 403
    first = await api.post(
        f"{URL}/initial",
        headers=a.owner,
        json={"product_id": empty["id"], "quantity": "5", "unit_cost": "120"},
    )
    assert first.status_code == HTTPStatus.CREATED, first.text
    assert (
        first.json()["movement_type"],
        first.json()["quantity_after"],
        first.json()["total_cost"],
    ) == ("INITIAL", "5.000", "600.00")
    again = await api.post(
        f"{URL}/initial",
        headers=a.owner,
        json={"product_id": empty["id"], "quantity": "5", "unit_cost": "120"},
    )
    assert (
        again.status_code == HTTPStatus.CONFLICT and error_code(again) == "PRODUCT_ALREADY_STOCKED"
    )
    stocked = await make_product(api, a.owner, name="Stocked", stock="3")
    assert (
        error_code(
            await api.post(
                f"{URL}/initial",
                headers=a.owner,
                json={"product_id": stocked["id"], "quantity": "1", "unit_cost": "1"},
            )
        )
        == "PRODUCT_ALREADY_STOCKED"
    )
    assert len(await _audits(db_session, a.business_id, "inventory.initial")) == 1


# --- history -------------------------------------------------------------------------------


async def test_movement_history_is_scoped_and_filtered(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """Ordering is covered in test_inventory_concurrency.py (needs real commit timestamps)."""
    a, b = tenants
    p = await make_product(api, a.owner, stock="10")
    q = await make_product(api, a.owner, name="Other", stock="1")
    foreign = await make_product(api, b.owner, stock="7")
    await restock(api, a.owner, p["id"], "5")
    await sell(api, a.owner, sale_payload([(p["id"], "2")], [("CASH", "1000")]))
    await adjust(api, a.owner, p["id"], "-1")

    all_rows = (await api.get(f"{URL}/movements", headers=a.owner)).json()
    assert sorted(m["movement_type"] for m in all_rows) == [
        "ADJUSTMENT",
        "INITIAL",
        "INITIAL",
        "RESTOCK",
        "SALE",
    ]
    assert all(m["product_id"] != foreign["id"] for m in all_rows)
    for_p = (
        await api.get(f"{URL}/movements", headers=a.owner, params={"product_id": p["id"]})
    ).json()
    assert sorted(m["quantity_after"] for m in for_p) == ["10.000", "12.000", "13.000", "15.000"]
    assert all(m["product_id"] == p["id"] for m in for_p)
    sales_only = (
        await api.get(f"{URL}/movements", headers=a.owner, params={"movement_type": "SALE"})
    ).json()
    assert [m["quantity_delta"] for m in sales_only] == ["-2.000"] and sales_only[0][
        "sale_id"
    ] is not None
    assert (
        len((await api.get(f"{URL}/movements", headers=a.owner, params={"limit": 2})).json()) == 2
    )
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert (
        await api.get(f"{URL}/movements", headers=a.owner, params={"date_from": tomorrow})
    ).json() == []
    assert (
        await api.get(f"{URL}/movements", headers=a.owner, params={"movement_type": "THEFT"})
    ).status_code == 422
    # A foreign product id is not found, never an empty list; STAFF may read.
    assert (
        await api.get(f"{URL}/movements", headers=a.owner, params={"product_id": foreign["id"]})
    ).status_code == 404
    assert a.staff is not None
    assert (
        await api.get(f"{URL}/movements", headers=a.staff, params={"product_id": q["id"]})
    ).status_code == 200


# --- low stock ------------------------------------------------------------------------


async def test_low_stock_uses_product_threshold_or_business_default(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    assert a.staff is not None
    await make_product(api, a.owner, name="Fine", stock="50")
    low_default = await make_product(
        api, a.owner, name="Low by default", stock="5"
    )  # default threshold 5
    low_own = await make_product(
        api, a.owner, name="Low by own", stock="20", low_stock_threshold="20"
    )
    await make_product(
        api, a.owner, name="High own threshold ok", stock="30", low_stock_threshold="10"
    )
    await make_product(
        api, a.owner, name="Service", stock=None, tracked=False
    )  # stock 0 but untracked
    archived = await make_product(api, a.owner, name="Archived low", stock="1")
    await api.patch(f"{PRODUCTS_URL}/{archived['id']}", headers=a.owner, json={"is_active": False})
    await make_product(api, b.owner, name="Foreign low", stock=None)

    rows = (await api.get(f"{URL}/low-stock", headers=a.staff)).json()
    assert [(r["name"], r["stock_quantity"], r["threshold"]) for r in rows] == [
        ("Low by default", "5.000", "5.000"),
        ("Low by own", "20.000", "20.000"),
    ]
    assert rows[0]["product_id"] == low_default["id"] and rows[1]["product_id"] == low_own["id"]
    # Raising the business default pulls in products without their own threshold only.
    patched = await api.patch(
        BUSINESS_URL, headers=a.owner, json={"settings": {"low_stock_default_threshold": 60}}
    )
    assert patched.status_code == 200
    names = [r["name"] for r in (await api.get(f"{URL}/low-stock", headers=a.owner)).json()]
    assert names == ["Low by default", "Fine", "Low by own"]  # by (stock - threshold): -55, -10, 0
    assert "Foreign low" not in names and "Archived low" not in names and "Service" not in names
    assert "High own threshold ok" not in names  # its own threshold (10) still applies


# --- recompute ----------------------------------------------------------------------------


async def test_recompute_reports_and_repairs_cache_drift(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner, stock="10")
    await sell(api, a.owner, sale_payload([(p["id"], "3")], [("CASH", "1500")]))
    clean = await api.post(f"{URL}/recompute", headers=a.owner, json={"apply": False})
    assert clean.status_code == HTTPStatus.OK and clean.json() == {
        "products_checked": 1,
        "discrepancies": [],
        "applied": False,
    }
    # Corrupt the cache behind the API's back.
    product = await db_session.get(Product, uuid.UUID(p["id"]))
    assert product is not None
    product.stock_quantity = D("99")
    await db_session.flush()
    report = (await api.post(f"{URL}/recompute", headers=a.owner, json={"apply": False})).json()
    assert report["discrepancies"] == [
        {
            "product_id": p["id"],
            "cached_stock": "99.000",
            "ledger_stock": "7.000",
            "repaired": False,
        }
    ]
    await db_session.refresh(product)
    assert product.stock_quantity == D("99.000")  # dry run changed nothing
    fixed = (await api.post(f"{URL}/recompute", headers=a.owner, json={"apply": True})).json()
    assert fixed["discrepancies"][0]["repaired"] is True and fixed["applied"] is True
    await db_session.refresh(product)
    assert product.stock_quantity == D("7.000")
    rows = await _audits(db_session, a.business_id, "inventory.recompute")
    assert (
        len(rows) == 1
        and rows[0].before == {"stock_quantity": "99.000"}
        and rows[0].after == {"stock_quantity": "7.000"}
    )
    # No movement was written by the repair; the ledger is untouched.
    movements = (
        await db_session.scalars(
            select(InventoryMovement).where(InventoryMovement.product_id == product.id)
        )
    ).all()
    assert sorted(m.movement_type.value for m in movements) == ["INITIAL", "SALE"]
    assert (
        await api.post(f"{URL}/recompute", headers=a.staff, json={"apply": True})
    ).status_code == 403


# --- atomicity / lifecycle ----------------------------------------------------------------


async def test_failure_after_the_movement_rolls_back_cache_and_audit(
    api: AsyncClient,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, stock="10")
    real_record = audit_service.record

    async def record_then_fail(*args: object, **kwargs: object) -> object:
        await real_record(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("simulated failure after audit")

    monkeypatch.setattr("app.services.inventory.audit.record", record_then_fail)
    assert (
        await restock(api, a.owner, p["id"], "5")
    ).status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert (
        await adjust(api, a.owner, p["id"], "-1")
    ).status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert await stock_of(db_session, p["id"]) == D("10.000")
    movements = (
        await db_session.scalars(
            select(InventoryMovement)
            .where(InventoryMovement.product_id == uuid.UUID(p["id"]))
            .execution_options(populate_existing=True)
        )
    ).all()
    assert [m.movement_type.value for m in movements] == ["INITIAL"]
    assert await _audits(db_session, a.business_id, "inventory.restock") == []
    assert await _audits(db_session, a.business_id, "inventory.adjust") == []


async def test_unauthenticated_and_inactive_business(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, stock="1")
    assert (await api.get(f"{URL}/movements")).status_code == 401
    assert (
        await api.post(
            f"{URL}/restock", json={"product_id": p["id"], "quantity": "1", "unit_cost": "1"}
        )
    ).status_code == 401
    await set_business_active(db_session, uuid.UUID(a.business_id), False)
    for call in (
        api.get(f"{URL}/movements", headers=a.owner),
        api.get(f"{URL}/low-stock", headers=a.owner),
        restock(api, a.owner, p["id"], "1"),
        adjust(api, a.owner, p["id"], "1"),
    ):
        response = await call
        assert (
            response.status_code == HTTPStatus.FORBIDDEN
            and error_code(response) == "BUSINESS_INACTIVE"
        )
