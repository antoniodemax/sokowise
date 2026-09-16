"""/api/v1/categories (PRD FR-D4; DATA_MAPPING §3.5)."""

import uuid
from http import HTTPStatus

import pytest
from app.models import Category
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import error_code, set_business_active
from tests.db.isolation import Tenant

pytestmark = [pytest.mark.db, pytest.mark.anyio]

URL = "/api/v1/categories"
PRODUCTS_URL = "/api/v1/products"


async def _create(api: AsyncClient, headers: dict[str, str], name: str) -> dict[str, object]:
    response = await api.post(URL, headers=headers, json={"name": name})
    assert response.status_code == HTTPStatus.CREATED, response.text
    body: dict[str, object] = response.json()
    return body


async def test_owner_creates_lists_gets_updates_and_deletes(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    drinks = await _create(api, a.owner, "  Drinks  ")
    assert drinks["name"] == "Drinks"  # trimmed
    assert set(drinks) == {"id", "name", "created_at", "updated_at"}
    food = await _create(api, a.owner, "food")

    listing = await api.get(URL, headers=a.owner)
    assert listing.status_code == HTTPStatus.OK
    assert [c["name"] for c in listing.json()] == ["Drinks", "food"]  # case-insensitive order

    one = await api.get(f"{URL}/{drinks['id']}", headers=a.owner)
    assert one.status_code == HTTPStatus.OK and one.json()["name"] == "Drinks"

    renamed = await api.patch(f"{URL}/{drinks['id']}", headers=a.owner, json={"name": "Beverages"})
    assert renamed.status_code == HTTPStatus.OK and renamed.json()["name"] == "Beverages"

    deleted = await api.delete(f"{URL}/{food['id']}", headers=a.owner)
    assert deleted.status_code == HTTPStatus.NO_CONTENT
    assert (
        await api.get(f"{URL}/{food['id']}", headers=a.owner)
    ).status_code == HTTPStatus.NOT_FOUND
    rows = (await db_session.scalars(select(Category))).all()
    assert {r.name for r in rows if r.business_id == uuid.UUID(a.business_id)} == {"Beverages"}


async def test_staff_can_read_but_not_write(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    drinks = await _create(api, a.owner, "Drinks")
    assert (await api.get(URL, headers=a.staff)).status_code == HTTPStatus.OK
    assert (await api.get(f"{URL}/{drinks['id']}", headers=a.staff)).status_code == HTTPStatus.OK
    for call in (
        api.post(URL, headers=a.staff, json={"name": "Snacks"}),
        api.patch(f"{URL}/{drinks['id']}", headers=a.staff, json={"name": "X"}),
        api.delete(f"{URL}/{drinks['id']}", headers=a.staff),
    ):
        response = await call
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert error_code(response) == "FORBIDDEN"
    assert (await api.get(f"{URL}/{drinks['id']}", headers=a.owner)).json()["name"] == "Drinks"


async def test_unauthenticated_is_401(api: AsyncClient) -> None:
    assert (await api.get(URL)).status_code == HTTPStatus.UNAUTHORIZED
    assert (await api.post(URL, json={"name": "x"})).status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize(
    "payload",
    [{"name": ""}, {"name": "   "}, {"name": "x" * 61}, {}, {"name": "ok", "business_id": "x"}],
)
async def test_invalid_names_are_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], payload: dict[str, object]
) -> None:
    a, _ = tenants
    response = await api.post(URL, headers=a.owner, json=payload)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, payload
    assert error_code(response) == "VALIDATION_ERROR"


async def test_duplicate_name_is_a_409_case_insensitively(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    drinks = await _create(api, a.owner, "Drinks")
    dup = await api.post(URL, headers=a.owner, json={"name": "DRINKS"})
    assert dup.status_code == HTTPStatus.CONFLICT
    assert error_code(dup) == "CATEGORY_EXISTS"
    food = await _create(api, a.owner, "Food")
    clash = await api.patch(f"{URL}/{food['id']}", headers=a.owner, json={"name": "drinks"})
    assert clash.status_code == HTTPStatus.CONFLICT
    assert error_code(clash) == "CATEGORY_EXISTS"
    assert r"psycopg\|asyncpg\|constraint" not in dup.text
    assert (await api.get(f"{URL}/{drinks['id']}", headers=a.owner)).json()["name"] == "Drinks"


async def test_same_name_in_two_businesses_is_fine(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    first = await _create(api, a.owner, "Drinks")
    second = await _create(api, b.owner, "Drinks")
    assert first["id"] != second["id"]
    assert [c["name"] for c in (await api.get(URL, headers=a.owner)).json()] == ["Drinks"]
    assert [c["id"] for c in (await api.get(URL, headers=b.owner)).json()] == [second["id"]]


async def test_category_in_use_cannot_be_deleted(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    drinks = await _create(api, a.owner, "Drinks")
    product = await api.post(
        PRODUCTS_URL,
        headers=a.owner,
        json={"name": "Soda", "selling_price": "50", "category_id": drinks["id"]},
    )
    assert product.status_code == HTTPStatus.CREATED, product.text
    blocked = await api.delete(f"{URL}/{drinks['id']}", headers=a.owner)
    assert blocked.status_code == HTTPStatus.CONFLICT
    assert error_code(blocked) == "CATEGORY_IN_USE"
    assert blocked.json()["error"]["details"] == {"products": 1}
    # Archived products still count: the label must survive for history.
    archived = await api.patch(
        f"{PRODUCTS_URL}/{product.json()['id']}", headers=a.owner, json={"is_active": False}
    )
    assert archived.status_code == HTTPStatus.OK
    assert (
        await api.delete(f"{URL}/{drinks['id']}", headers=a.owner)
    ).status_code == HTTPStatus.CONFLICT
    # Moving the product off the category frees it.
    assert (
        await api.patch(
            f"{PRODUCTS_URL}/{product.json()['id']}", headers=a.owner, json={"category_id": None}
        )
    ).status_code == HTTPStatus.OK
    assert (
        await api.delete(f"{URL}/{drinks['id']}", headers=a.owner)
    ).status_code == HTTPStatus.NO_CONTENT


async def test_inactive_business_blocks_categories(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    await set_business_active(db_session, uuid.UUID(a.business_id), False)
    response = await api.get(URL, headers=a.owner)
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert error_code(response) == "BUSINESS_INACTIVE"
