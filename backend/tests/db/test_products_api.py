"""/api/v1/products (PRD FR-D1-FR-D6, FR-E1, §16; DATA_MAPPING §3.6-§3.7)."""

import uuid
from decimal import Decimal
from http import HTTPStatus
from typing import Any

import pytest
from app.models import AuditLog, InventoryMovement, Product
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import error_code
from tests.db.isolation import Tenant

pytestmark = [pytest.mark.db, pytest.mark.anyio]

URL = "/api/v1/products"
CATEGORIES_URL = "/api/v1/categories"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": "Sugar 1kg", "selling_price": "150.00"}
    payload.update(overrides)
    return payload


async def _create(api: AsyncClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    response = await api.post(URL, headers=headers, json=_payload(**overrides))
    assert response.status_code == HTTPStatus.CREATED, response.text
    body: dict[str, Any] = response.json()
    return body


async def _category(api: AsyncClient, headers: dict[str, str], name: str = "Groceries") -> str:
    response = await api.post(CATEGORIES_URL, headers=headers, json={"name": name})
    assert response.status_code == HTTPStatus.CREATED, response.text
    category_id: str = response.json()["id"]
    return category_id


async def _movements(session: AsyncSession, product_id: str) -> list[InventoryMovement]:
    result = await session.scalars(
        select(InventoryMovement)
        .where(InventoryMovement.product_id == uuid.UUID(product_id))
        .execution_options(populate_existing=True)
    )
    return list(result)


async def _audits(session: AsyncSession, business_id: str) -> list[AuditLog]:
    result = await session.scalars(
        select(AuditLog)
        .where(AuditLog.business_id == uuid.UUID(business_id))
        .execution_options(populate_existing=True)
    )
    return list(result)


# --- create -----------------------------------------------------------------------------


async def test_create_with_defaults(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    body = await _create(api, a.owner)
    assert body["name"] == "Sugar 1kg"
    assert body["selling_price"] == "150.00"  # money is a string, never a float
    assert body["cost_price"] is None
    assert body["unit"] == "piece"
    assert body["track_inventory"] is True
    assert body["stock_quantity"] == "0.000"
    assert body["is_active"] is True
    assert body["category_id"] is None and body["sku"] is None and body["barcode"] is None
    assert set(body) == {
        "id",
        "name",
        "category_id",
        "sku",
        "barcode",
        "unit",
        "selling_price",
        "cost_price",
        "track_inventory",
        "stock_quantity",
        "low_stock_threshold",
        "is_active",
        "created_at",
        "updated_at",
    }


async def test_create_with_every_field_and_category(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    category_id = await _category(api, a.owner)
    body = await _create(
        api,
        a.owner,
        name="  Cooking Oil 1L ",
        category_id=category_id,
        sku=" OIL-1L ",
        barcode="6161100000012",
        unit="litre",
        selling_price=320,
        cost_price="280.50",
        low_stock_threshold="5",
    )
    assert body["name"] == "Cooking Oil 1L"
    assert body["sku"] == "OIL-1L"
    assert body["category_id"] == category_id
    assert body["unit"] == "litre"
    assert body["selling_price"] == "320.00"
    assert body["cost_price"] == "280.50"
    assert body["low_stock_threshold"] == "5.000"


async def test_opening_stock_writes_an_initial_movement_atomically(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    body = await _create(
        api,
        a.owner,
        name="Rice 2kg",
        cost_price="200",
        opening_stock="12.5",
        opening_unit_cost="190",
    )
    assert body["stock_quantity"] == "12.500"
    movements = await _movements(db_session, body["id"])
    assert len(movements) == 1
    m = movements[0]
    assert m.movement_type.value == "INITIAL"
    assert (m.quantity_delta, m.quantity_after) == (Decimal("12.500"), Decimal("12.500"))
    assert (m.unit_cost, m.total_cost) == (Decimal("190.00"), Decimal("2375.00"))
    assert m.business_id == uuid.UUID(a.business_id)
    assert m.created_by == uuid.UUID(a.owner_user_id)
    assert m.sale_id is None and m.reason is None
    product = await db_session.get(Product, uuid.UUID(body["id"]))
    assert product is not None and product.stock_quantity == Decimal("12.500")


async def test_opening_unit_cost_defaults_to_cost_price(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    body = await _create(api, a.owner, cost_price="120", opening_stock="3")
    (m,) = await _movements(db_session, body["id"])
    assert (m.unit_cost, m.total_cost) == (Decimal("120.00"), Decimal("360.00"))


async def test_no_opening_stock_means_no_movement(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    body = await _create(api, a.owner)
    assert await _movements(db_session, body["id"]) == []


async def test_untracked_product_never_gets_stock(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    body = await _create(api, a.owner, name="Haircut", unit="service", track_inventory=False)
    assert body["stock_quantity"] == "0.000"
    assert await _movements(db_session, body["id"]) == []
    rejected = await api.post(
        URL,
        headers=a.owner,
        json=_payload(
            name="Shave", track_inventory=False, opening_stock="5", opening_unit_cost="1"
        ),
    )
    assert rejected.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert error_code(rejected) == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 121},
        {"selling_price": "-1"},
        {"selling_price": "10.123"},  # three decimals on money
        {"selling_price": "1234567890123.00"},  # more than 14 digits
        {"selling_price": "abc"},
        {"cost_price": "-0.01"},
        {"unit": "bottle"},
        {"low_stock_threshold": "-1"},
        {"low_stock_threshold": "1.2345"},
        {"opening_stock": "0"},
        {"opening_stock": "-2", "opening_unit_cost": "1"},
        {"opening_stock": "5"},  # no unit cost and no cost_price
        {"opening_unit_cost": "5"},  # without opening_stock
        {"stock_quantity": "5"},  # never writable (FR-D6)
        {"business_id": str(uuid.uuid4())},
        {"category_id": "not-a-uuid"},
    ],
)
async def test_invalid_create_payloads_are_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], overrides: dict[str, Any]
) -> None:
    a, _ = tenants
    response = await api.post(URL, headers=a.owner, json=_payload(**overrides))
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, (overrides, response.text)
    assert error_code(response) == "VALIDATION_ERROR"


async def test_missing_selling_price_is_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    response = await api.post(URL, headers=a.owner, json={"name": "No price"})
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


# --- uniqueness ---------------------------------------------------------------------------


async def test_active_name_is_unique_per_business_case_insensitively(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    first = await _create(api, a.owner, name="Sugar 1kg")
    dup = await api.post(URL, headers=a.owner, json=_payload(name="SUGAR 1KG"))
    assert dup.status_code == HTTPStatus.CONFLICT
    assert error_code(dup) == "PRODUCT_NAME_EXISTS"
    # Another business may use the same name.
    assert (await _create(api, b.owner, name="Sugar 1kg"))["id"] != first["id"]
    # Archiving the first frees the name; a new active product may take it.
    assert (
        await api.patch(f"{URL}/{first['id']}", headers=a.owner, json={"is_active": False})
    ).status_code == HTTPStatus.OK
    replacement = await _create(api, a.owner, name="sugar 1kg")
    # ...and the archived one can no longer come back under that name.
    revive = await api.patch(f"{URL}/{first['id']}", headers=a.owner, json={"is_active": True})
    assert revive.status_code == HTTPStatus.CONFLICT
    assert error_code(revive) == "PRODUCT_NAME_EXISTS"
    assert replacement["is_active"] is True


async def test_sku_and_barcode_are_unique_per_business_and_optional(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    await _create(api, a.owner, name="A1", sku="SKU001", barcode="111")
    for overrides, code in (
        ({"name": "A2", "sku": "SKU001"}, "SKU_EXISTS"),
        ({"name": "A3", "barcode": "111"}, "BARCODE_EXISTS"),
    ):
        response = await api.post(URL, headers=a.owner, json=_payload(**overrides))
        assert response.status_code == HTTPStatus.CONFLICT, overrides
        assert error_code(response) == code
    # Same SKU in another business is fine; many products without a SKU are fine.
    await _create(api, b.owner, name="B1", sku="SKU001", barcode="111")
    await _create(api, a.owner, name="A4")
    await _create(api, a.owner, name="A5", sku="")  # blank clears to null
    assert len((await api.get(URL, headers=a.owner)).json()) == 3
    # Archived products keep their SKU reserved (the index is not partial on is_active).
    archived = await _create(api, a.owner, name="A6", sku="SKU002")
    await api.patch(f"{URL}/{archived['id']}", headers=a.owner, json={"is_active": False})
    clash = await api.post(URL, headers=a.owner, json=_payload(name="A7", sku="SKU002"))
    assert clash.status_code == HTTPStatus.CONFLICT and error_code(clash) == "SKU_EXISTS"


# --- category relationship --------------------------------------------------------------


async def test_category_from_another_business_is_not_found(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    foreign = await _category(api, b.owner, "Beta Drinks")
    response = await api.post(URL, headers=a.owner, json=_payload(category_id=foreign))
    assert response.status_code == HTTPStatus.NOT_FOUND, response.text
    assert error_code(response) == "NOT_FOUND"
    assert "Beta" not in response.text
    assert (await api.get(URL, headers=a.owner)).json() == []  # nothing was created
    # Same via PATCH, and a category that does not exist at all looks identical.
    product = await _create(api, a.owner)
    for category_id in (foreign, str(uuid.uuid4())):
        patched = await api.patch(
            f"{URL}/{product['id']}", headers=a.owner, json={"category_id": category_id}
        )
        assert patched.status_code == HTTPStatus.NOT_FOUND
    assert (await api.get(f"{URL}/{product['id']}", headers=a.owner)).json()["category_id"] is None


async def test_category_can_be_set_and_cleared(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    category_id = await _category(api, a.owner)
    product = await _create(api, a.owner)
    assert (
        await api.patch(
            f"{URL}/{product['id']}", headers=a.owner, json={"category_id": category_id}
        )
    ).json()["category_id"] == category_id
    listed = await api.get(URL, headers=a.owner, params={"category_id": category_id})
    assert [p["id"] for p in listed.json()] == [product["id"]]
    assert (
        await api.patch(f"{URL}/{product['id']}", headers=a.owner, json={"category_id": None})
    ).json()["category_id"] is None


# --- read / list / search -----------------------------------------------------------------


async def test_list_and_search(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, b = tenants
    await _create(api, a.owner, name="Sugar 1kg", sku="SUG1")
    await _create(api, a.owner, name="sugar 2kg", sku="SUG2", barcode="9900")
    await _create(api, a.owner, name="Bread", barcode="9901")
    archived = await _create(api, a.owner, name="Old Item")
    await api.patch(f"{URL}/{archived['id']}", headers=a.owner, json={"is_active": False})
    await _create(api, b.owner, name="Sugar 1kg")  # another tenant, same name

    listed = (await api.get(URL, headers=a.owner)).json()
    assert [p["name"] for p in listed] == ["Bread", "Sugar 1kg", "sugar 2kg"]
    everything = (await api.get(URL, headers=a.owner, params={"include_archived": "true"})).json()
    assert [p["name"] for p in everything] == ["Bread", "Old Item", "Sugar 1kg", "sugar 2kg"]
    assert all(p["id"] != archived["id"] for p in listed)

    by_name = (await api.get(URL, headers=a.owner, params={"q": "sug"})).json()
    assert [p["name"] for p in by_name] == ["Sugar 1kg", "sugar 2kg"]
    by_sku = (await api.get(URL, headers=a.owner, params={"q": "sug2"})).json()
    assert [p["name"] for p in by_sku] == ["sugar 2kg"]
    by_barcode = (await api.get(URL, headers=a.owner, params={"q": "990"})).json()
    assert [p["name"] for p in by_barcode] == ["Bread", "sugar 2kg"]
    assert (await api.get(URL, headers=a.owner, params={"q": "%"})).json() == []  # literal
    limited = (await api.get(URL, headers=a.owner, params={"limit": 1})).json()
    assert len(limited) == 1
    assert (await api.get(URL, headers=a.owner, params={"limit": 0})).status_code == 422


async def test_staff_can_read_but_not_write(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    product = await _create(api, a.owner)
    assert (await api.get(URL, headers=a.staff)).status_code == HTTPStatus.OK
    one = await api.get(f"{URL}/{product['id']}", headers=a.staff)
    assert one.status_code == HTTPStatus.OK and one.json()["selling_price"] == "150.00"
    for call in (
        api.post(URL, headers=a.staff, json=_payload(name="Staff product")),
        api.patch(f"{URL}/{product['id']}", headers=a.staff, json={"selling_price": "1"}),
        api.patch(f"{URL}/{product['id']}", headers=a.staff, json={"is_active": False}),
    ):
        response = await call
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert error_code(response) == "FORBIDDEN"
    assert (await api.get(f"{URL}/{product['id']}", headers=a.owner)).json()[
        "selling_price"
    ] == "150.00"


async def test_unauthenticated_is_401(api: AsyncClient) -> None:
    assert (await api.get(URL)).status_code == HTTPStatus.UNAUTHORIZED
    assert (await api.post(URL, json=_payload())).status_code == HTTPStatus.UNAUTHORIZED
    assert (await api.get(f"{URL}/{uuid.uuid4()}")).status_code == HTTPStatus.UNAUTHORIZED


async def test_unknown_product_is_404(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    missing = uuid.uuid4()
    assert (await api.get(f"{URL}/{missing}", headers=a.owner)).status_code == HTTPStatus.NOT_FOUND
    patched = await api.patch(f"{URL}/{missing}", headers=a.owner, json={"name": "x"})
    assert patched.status_code == HTTPStatus.NOT_FOUND


# --- update / lifecycle -------------------------------------------------------------------


async def test_update_fields_and_audit_price_changes_only(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    product = await _create(api, a.owner, cost_price="100")
    renamed = await api.patch(
        f"{URL}/{product['id']}",
        headers=a.owner,
        json={"name": "Sugar 1kg (Mumias)", "sku": "MUM1"},
    )
    assert renamed.status_code == HTTPStatus.OK
    assert renamed.json()["name"] == "Sugar 1kg (Mumias)"
    assert await _audits(db_session, a.business_id) == []  # not a financial change

    repriced = await api.patch(
        f"{URL}/{product['id']}", headers=a.owner, json={"selling_price": "160", "cost_price": None}
    )
    assert repriced.status_code == HTTPStatus.OK
    assert repriced.json()["selling_price"] == "160.00" and repriced.json()["cost_price"] is None
    rows = await _audits(db_session, a.business_id)
    assert len(rows) == 1
    assert rows[0].action == "product.price_change"
    assert rows[0].entity_type == "product" and rows[0].entity_id == uuid.UUID(product["id"])
    assert rows[0].actor_user_id == uuid.UUID(a.owner_user_id)
    assert rows[0].before == {"selling_price": "150.00", "cost_price": "100.00"}
    assert rows[0].after == {"selling_price": "160", "cost_price": None}

    # Same price again: no new row.
    await api.patch(f"{URL}/{product['id']}", headers=a.owner, json={"selling_price": "160.00"})
    assert len(await _audits(db_session, a.business_id)) == 1


async def test_archive_and_unarchive_are_audited_and_hide_from_lists(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    product = await _create(api, a.owner, opening_stock="4", opening_unit_cost="10")
    archived = await api.patch(f"{URL}/{product['id']}", headers=a.owner, json={"is_active": False})
    assert archived.status_code == HTTPStatus.OK and archived.json()["is_active"] is False
    assert (await api.get(URL, headers=a.owner)).json() == []
    # Still readable by id, with its stock and history intact.
    direct = await api.get(f"{URL}/{product['id']}", headers=a.owner)
    assert direct.status_code == HTTPStatus.OK and direct.json()["stock_quantity"] == "4.000"
    assert len(await _movements(db_session, product["id"])) == 1

    revived = await api.patch(f"{URL}/{product['id']}", headers=a.owner, json={"is_active": True})
    assert revived.status_code == HTTPStatus.OK
    assert [p["id"] for p in (await api.get(URL, headers=a.owner)).json()] == [product["id"]]

    rows = await _audits(db_session, a.business_id)
    assert {(r.action, str(r.before), str(r.after)) for r in rows} == {
        ("product.archive", "{'is_active': True}", "{'is_active': False}"),
        ("product.unarchive", "{'is_active': False}", "{'is_active': True}"),
    }


async def test_tracking_cannot_be_switched_off_while_stock_remains(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    stocked = await _create(api, a.owner, name="Stocked", opening_stock="2", opening_unit_cost="1")
    blocked = await api.patch(
        f"{URL}/{stocked['id']}", headers=a.owner, json={"track_inventory": False}
    )
    assert blocked.status_code == HTTPStatus.CONFLICT
    assert error_code(blocked) == "PRODUCT_HAS_STOCK"
    empty = await _create(api, a.owner, name="Empty")
    ok = await api.patch(f"{URL}/{empty['id']}", headers=a.owner, json={"track_inventory": False})
    assert ok.status_code == HTTPStatus.OK and ok.json()["track_inventory"] is False
    back = await api.patch(f"{URL}/{empty['id']}", headers=a.owner, json={"track_inventory": True})
    assert back.status_code == HTTPStatus.OK


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": None},
        {"selling_price": None},
        {"selling_price": "-5"},
        {"unit": None},
        {"is_active": None},
        {"stock_quantity": "9"},
        {"opening_stock": "9"},
        {"business_id": str(uuid.uuid4())},
    ],
)
async def test_invalid_update_payloads_are_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], payload: dict[str, Any]
) -> None:
    a, _ = tenants
    product = await _create(api, a.owner)
    response = await api.patch(f"{URL}/{product['id']}", headers=a.owner, json=payload)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, payload
    assert (await api.get(f"{URL}/{product['id']}", headers=a.owner)).json()[
        "stock_quantity"
    ] == "0.000"


async def test_price_change_never_touches_the_ledger(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """Movements keep their own unit_cost (as sale lines will): current cost is current only."""
    a, _ = tenants
    product = await _create(api, a.owner, cost_price="100", opening_stock="1")
    await api.patch(f"{URL}/{product['id']}", headers=a.owner, json={"cost_price": "999"})
    (m,) = await _movements(db_session, product["id"])
    assert m.unit_cost == Decimal("100.00")


async def test_tracking_stays_on_once_the_product_has_movements(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    """Otherwise voiding an old sale could no longer write its SALE_REVERSAL (FR-F7)."""
    from tests.db.sales_helpers import SALES_URL, make_product, sale_payload, sell

    a, _ = tenants
    fresh = await api.post(URL, headers=a.owner, json={"name": "Fresh", "selling_price": "10"})
    assert fresh.status_code == HTTPStatus.CREATED
    untrack = await api.patch(
        f"{URL}/{fresh.json()['id']}", headers=a.owner, json={"track_inventory": False}
    )
    assert untrack.status_code == HTTPStatus.OK  # no history: fine

    product_id = (await make_product(api, a.owner, name="Sold out", price="10", stock="2"))["id"]
    sale = await sell(api, a.owner, sale_payload([(product_id, "2")], [("CASH", "20")]))
    blocked = await api.patch(
        f"{URL}/{product_id}", headers=a.owner, json={"track_inventory": False}
    )
    assert blocked.status_code == HTTPStatus.CONFLICT
    assert error_code(blocked) == "PRODUCT_HAS_MOVEMENTS"
    void = await api.post(f"{SALES_URL}/{sale['id']}/void", headers=a.owner, json={"reason": "x"})
    assert void.status_code == HTTPStatus.OK, void.text


# --- starter catalogue and bulk create (PRD FR-N) -----------------------------------------


async def test_starter_list_follows_the_business_type_and_is_owner_only(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    assert (await api.get(f"{URL}/starter", headers=a.staff)).status_code == HTTPStatus.FORBIDDEN
    response = await api.get(f"{URL}/starter", headers=a.owner)
    assert response.status_code == HTTPStatus.OK, response.text
    items = response.json()
    names = [i["name"] for i in items]
    assert "Sukari 1kg" in names and names[-1] == "Other"  # default type is a general shop
    other = items[-1]
    assert other["track_inventory"] is False and other["selling_price"] == "0.00"
    assert all(i["selling_price"] is not None and i["unit"] for i in items)
    # Switching the business type changes the list.
    patched = await api.patch("/api/v1/business", headers=a.owner, json={"business_type": "SALON"})
    assert patched.status_code == HTTPStatus.OK, patched.text
    salon = [i["name"] for i in (await api.get(f"{URL}/starter", headers=a.owner)).json()]
    assert "Braiding" in salon and "Sukari 1kg" not in salon


async def test_bulk_create_is_all_or_nothing_and_names_the_bad_item(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    assert a.staff is not None
    items = [
        {"name": "Sukari 1kg", "selling_price": "160", "cost_price": "135", "opening_stock": "20"},
        {"name": "Airtime", "selling_price": "0", "track_inventory": False, "unit": "other"},
        {"name": "Mkate 400g", "selling_price": "60", "cost_price": "50"},
    ]
    staff = await api.post(f"{URL}/bulk", headers=a.staff, json={"items": items})
    assert staff.status_code == HTTPStatus.FORBIDDEN
    created = await api.post(f"{URL}/bulk", headers=a.owner, json={"items": items})
    assert created.status_code == HTTPStatus.CREATED, created.text
    rows = created.json()
    assert [r["name"] for r in rows] == ["Sukari 1kg", "Airtime", "Mkate 400g"]
    assert rows[0]["stock_quantity"] == "20.000" and rows[1]["track_inventory"] is False
    # The opening stock wrote an INITIAL movement like a single create would.
    movements = await api.get(
        f"/api/v1/inventory/movements?product_id={rows[0]['id']}", headers=a.owner
    )
    assert [m["movement_type"] for m in movements.json()] == ["INITIAL"]

    # A duplicate in position 2 rolls back the whole batch, including the new product at 1.
    clash = await api.post(
        f"{URL}/bulk",
        headers=a.owner,
        json={
            "items": [
                {"name": "Maziwa 500ml", "selling_price": "65"},
                {"name": "sukari 1KG", "selling_price": "1"},  # case-insensitive duplicate
            ]
        },
    )
    assert clash.status_code == HTTPStatus.CONFLICT, clash.text
    body = clash.json()["error"]
    assert body["code"] == "PRODUCT_NAME_EXISTS" and body["details"] == {
        "index": 1,
        "name": "sukari 1KG",
    }
    assert body["message"].startswith("Item 2 (sukari 1KG)")
    listed = [p["name"] for p in (await api.get(URL, headers=a.owner)).json()]
    assert "Maziwa 500ml" not in listed and len(listed) == 3
    # Tenant B is untouched and cannot see A's products.
    assert (await api.get(URL, headers=b.owner)).json() == []


@pytest.mark.parametrize(
    "items",
    [[], [{"name": "x", "selling_price": "1"}] * 101, [{"name": "", "selling_price": "1"}]],
)
async def test_bulk_create_validation(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], items: list[dict[str, str]]
) -> None:
    a, _ = tenants
    response = await api.post(f"{URL}/bulk", headers=a.owner, json={"items": items})
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
