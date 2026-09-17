"""Every tenant-scoped endpoint, run through the isolation helper (ROADMAP Phase 4).

To register a new resource type, add an `IsolationCase` to `CASES`. Registered:
business members (Phase 4), categories and products (Phase 5), customers (Phase 6),
customer accounts — ledger, repayments, adjustments (Phase 7), sales (Phase 8), inventory
movements (Phase 9), expenses (Phase 10).
"""

import uuid
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
CUSTOMERS_URL = "/api/v1/customers"
SALES_URL = "/api/v1/sales"
INVENTORY_URL = "/api/v1/inventory"
EXPENSES_URL = "/api/v1/expenses"


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


async def _create_customer(api: AsyncClient, session: AsyncSession, tenant: Tenant) -> str:
    response = await api.post(
        CUSTOMERS_URL, headers=tenant.owner, json={"name": "Mama Njeri", "phone": "0712345678"}
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    customer_id: str = response.json()["id"]
    return customer_id


async def _create_debtor(api: AsyncClient, session: AsyncSession, tenant: Tenant) -> str:
    """A customer who owes 500, so the account endpoints have something to protect."""
    customer_id = await _create_customer(api, session, tenant)
    response = await api.post(
        f"{CUSTOMERS_URL}/{customer_id}/adjustments",
        headers=tenant.owner,
        json={"amount": "500", "direction": "INCREASE", "reason": "opening balance"},
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    return customer_id


async def _create_sale(api: AsyncClient, session: AsyncSession, tenant: Tenant) -> str:
    product_id = await _create_product(api, session, tenant)
    response = await api.post(
        SALES_URL,
        headers={**tenant.owner, "Idempotency-Key": str(uuid.uuid4())},
        json={
            "lines": [{"product_id": product_id, "quantity": "1"}],
            "payments": [{"method": "CASH", "amount": "150"}],
        },
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    sale_id: str = response.json()["id"]
    return sale_id


async def _create_stocked_product(api: AsyncClient, session: AsyncSession, tenant: Tenant) -> str:
    """A product with opening stock: its movement history is the tenant-owned resource."""
    response = await api.post(
        PRODUCTS_URL,
        headers=tenant.owner,
        json={
            "name": "Stocked",
            "selling_price": "10",
            "opening_stock": "5",
            "opening_unit_cost": "1",
        },
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    product_id: str = response.json()["id"]
    return product_id


async def _create_expense(api: AsyncClient, session: AsyncSession, tenant: Tenant) -> str:
    response = await api.post(
        EXPENSES_URL,
        headers=tenant.owner,
        json={"amount": "250", "category": "RENT", "payment_method": "CASH"},
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    expense_id: str = response.json()["id"]
    return expense_id


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
    IsolationCase(
        name="customers",
        create_in=_create_customer,
        read_url=lambda customer_id: f"{CUSTOMERS_URL}/{customer_id}",
        # Search by the exact phone must not surface another tenant's customer either.
        list_url=f"{CUSTOMERS_URL}?include_archived=true&q=0712345678",
    ),
    IsolationCase(
        name="customer-accounts",
        create_in=_create_debtor,
        read_url=lambda customer_id: f"{CUSTOMERS_URL}/{customer_id}/ledger",
        list_url="/api/v1/debtors",
        mutations=(
            (
                "POST",
                lambda customer_id: f"{CUSTOMERS_URL}/{customer_id}/repayments",
                {"amount": "1", "payment_method": "CASH"},
            ),
            (
                "POST",
                lambda customer_id: f"{CUSTOMERS_URL}/{customer_id}/adjustments",
                {"amount": "1", "direction": "INCREASE", "reason": "hijack"},
            ),
            (
                "POST",
                lambda customer_id: f"{CUSTOMERS_URL}/{customer_id}/adjustments",
                {"amount": "1", "direction": "DECREASE", "reason": "hijack"},
            ),
        ),
    ),
    IsolationCase(
        name="sales",
        create_in=_create_sale,
        read_url=lambda sale_id: f"{SALES_URL}/{sale_id}",
        list_url=SALES_URL,
        mutations=(("POST", lambda sale_id: f"{SALES_URL}/{sale_id}/void", {"reason": "hijack"}),),
    ),
    IsolationCase(
        name="inventory",
        create_in=_create_stocked_product,
        read_url=lambda product_id: f"{INVENTORY_URL}/movements?product_id={product_id}",
        list_url=f"{INVENTORY_URL}/movements",
        mutations=(
            (
                "POST",
                lambda product_id: f"{INVENTORY_URL}/restock",
                {"product_id": None, "quantity": "1", "unit_cost": "1"},
            ),
            (
                "POST",
                lambda product_id: f"{INVENTORY_URL}/adjust",
                {"product_id": None, "quantity_delta": "-1", "reason": "hijack"},
            ),
        ),
    ),
    IsolationCase(
        name="expenses",
        create_in=_create_expense,
        read_url=lambda expense_id: f"{EXPENSES_URL}/{expense_id}",
        list_url=f"{EXPENSES_URL}?include_deleted=true",
        mutations=(("PATCH", lambda expense_id: f"{EXPENSES_URL}/{expense_id}", {"amount": "1"}),),
        delete_url=lambda expense_id: f"{EXPENSES_URL}/{expense_id}",
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


async def test_list_filters_naming_another_tenants_resource_are_404(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """A filter is a lookup too: a foreign id must be 404, not a silently empty list."""
    a, b = tenants
    customer_id = await _create_customer(api, db_session, b)
    category_id = await _create_category(api, db_session, b)
    for url in (
        f"{SALES_URL}?customer_id={customer_id}",
        f"{PRODUCTS_URL}?category_id={category_id}",
    ):
        assert (await api.get(url, headers=b.owner)).status_code == HTTPStatus.OK, url
        foreign = await api.get(url, headers=a.owner)
        assert foreign.status_code == HTTPStatus.NOT_FOUND, (url, foreign.text)


async def test_initial_stock_for_another_tenants_product_is_404(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    product_id = await _create_product(api, db_session, b)
    response = await api.post(
        f"{INVENTORY_URL}/initial",
        headers=a.owner,
        json={"product_id": product_id, "quantity": "1", "unit_cost": "1"},
    )
    assert response.status_code == HTTPStatus.NOT_FOUND, response.text


async def test_timeseries_never_counts_another_tenants_sales(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    await _create_sale(api, db_session, b)
    own = await api.get("/api/v1/analytics/timeseries?period=today", headers=b.owner)
    other = await api.get("/api/v1/analytics/timeseries?period=today", headers=a.owner)
    assert own.status_code == other.status_code == HTTPStatus.OK
    assert sum(int(bucket["sales_count"]) for bucket in own.json()["buckets"]) == 1
    assert sum(int(bucket["sales_count"]) for bucket in other.json()["buckets"]) == 0
