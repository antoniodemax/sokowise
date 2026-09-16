"""Every tenant-scoped endpoint, run through the isolation helper (ROADMAP Phase 4).

To register a new resource type, add an `IsolationCase` to `CASES`. Registered:
business members (Phase 4), categories and products (Phase 5).
"""

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import OTHER_PASSWORD, PASSWORD, unique_phone
from tests.db.isolation import IsolationCase, Tenant, assert_tenant_isolated

pytestmark = [pytest.mark.db, pytest.mark.anyio]

USERS_URL = "/api/v1/users"
CATEGORIES_URL = "/api/v1/categories"
PRODUCTS_URL = "/api/v1/products"


async def _create_staff_member(api: AsyncClient, session: AsyncSession, tenant: Tenant) -> str:
    response = await api.post(
        USERS_URL,
        headers=tenant.owner,
        json={"full_name": "Isolated Staff", "phone": unique_phone(), "password": PASSWORD},
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    user_id: str = response.json()["user_id"]
    return user_id


async def _create_category(api: AsyncClient, session: AsyncSession, tenant: Tenant) -> str:
    response = await api.post(CATEGORIES_URL, headers=tenant.owner, json={"name": "Drinks"})
    assert response.status_code == HTTPStatus.CREATED, response.text
    category_id: str = response.json()["id"]
    return category_id


async def _create_product(api: AsyncClient, session: AsyncSession, tenant: Tenant) -> str:
    response = await api.post(
        PRODUCTS_URL,
        headers=tenant.owner,
        json={
            "name": "Sugar 1kg",
            "selling_price": "150",
            "sku": "SUG-1",
            "opening_stock": "3",
            "opening_unit_cost": "120",
        },
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    product_id: str = response.json()["id"]
    return product_id


CASES: list[IsolationCase] = [
    IsolationCase(
        name="users",
        create_in=_create_staff_member,
        read_url=lambda user_id: f"{USERS_URL}/{user_id}",
        list_url=USERS_URL,
        mutations=(
            ("PATCH", lambda user_id: f"{USERS_URL}/{user_id}", {"role": "OWNER"}),
            ("PATCH", lambda user_id: f"{USERS_URL}/{user_id}", {"is_active": False}),
            (
                "POST",
                lambda user_id: f"{USERS_URL}/{user_id}/reset-password",
                {"password": OTHER_PASSWORD},
            ),
        ),
    ),
    IsolationCase(
        name="categories",
        create_in=_create_category,
        read_url=lambda category_id: f"{CATEGORIES_URL}/{category_id}",
        list_url=CATEGORIES_URL,
        mutations=(
            ("PATCH", lambda category_id: f"{CATEGORIES_URL}/{category_id}", {"name": "X"}),
        ),
        delete_url=lambda category_id: f"{CATEGORIES_URL}/{category_id}",
    ),
    IsolationCase(
        name="products",
        create_in=_create_product,
        read_url=lambda product_id: f"{PRODUCTS_URL}/{product_id}",
        list_url=f"{PRODUCTS_URL}?include_archived=true",
        mutations=(
            ("PATCH", lambda product_id: f"{PRODUCTS_URL}/{product_id}", {"name": "Hijacked"}),
            ("PATCH", lambda product_id: f"{PRODUCTS_URL}/{product_id}", {"selling_price": "1"}),
            ("PATCH", lambda product_id: f"{PRODUCTS_URL}/{product_id}", {"is_active": False}),
        ),
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
async def test_tenant_isolation(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant], case: IsolationCase
) -> None:
    a, b = tenants
    await assert_tenant_isolated(api, db_session, case, a, b)
    # And in the other direction, so the check is not accidentally one-sided.
    await assert_tenant_isolated(api, db_session, case, b, a)
