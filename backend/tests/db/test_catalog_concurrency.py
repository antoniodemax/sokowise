"""Racing creates with the same name/SKU: the unique indexes decide (DATA_MAPPING §3.5-§3.6).

Real commits on separate connections; rows are cleaned up afterwards.
"""

from collections.abc import AsyncIterator
from http import HTTPStatus

import anyio
import pytest
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.db.auth_helpers import bearer, register
from tests.db.conftest import TEST_BASE_URL

pytestmark = [pytest.mark.db, pytest.mark.anyio]

PHONE_PREFIX = "+254707"
BUSINESS_NAME = "Catalog Race Duka"


@pytest.fixture
async def committed_api(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    get_settings.cache_clear()
    app = create_app(Settings())

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=TEST_BASE_URL) as api:
            yield api
    finally:
        async with engine.begin() as connection:
            params = {"name": BUSINESS_NAME, "prefix": PHONE_PREFIX + "%"}
            business = "(SELECT id FROM businesses WHERE name = :name)"
            for table in ("inventory_movements", "audit_logs", "products", "categories"):
                await connection.execute(
                    text(f"DELETE FROM {table} WHERE business_id IN {business}"),  # noqa: S608
                    params,
                )
            users = "(SELECT id FROM users WHERE phone LIKE :prefix)"
            for table in ("refresh_tokens", "business_memberships"):
                await connection.execute(
                    text(f"DELETE FROM {table} WHERE user_id IN {users}"),  # noqa: S608
                    params,
                )
            await connection.execute(text("DELETE FROM businesses WHERE name = :name"), params)
            await connection.execute(text("DELETE FROM users WHERE phone LIKE :prefix"), params)
        get_settings.cache_clear()


def _client(api: AsyncClient, ip: str) -> AsyncClient:
    transport = api._transport
    assert isinstance(transport, ASGITransport)
    return AsyncClient(
        transport=ASGITransport(app=transport.app, client=(ip, 40000)), base_url=TEST_BASE_URL
    )


async def _race(
    api: AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, object],
    n: int = 3,
) -> list[Response]:
    results: list[Response] = []

    async def attempt(ip: str) -> None:
        async with _client(api, ip) as client:
            results.append(await client.request(method, url, headers=headers, json=body))

    async with anyio.create_task_group() as tg:
        for i in range(n):
            tg.start_soon(attempt, f"10.5.0.{i}")
    return results


async def test_concurrent_category_creates_with_one_name_yield_one_row(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = bearer(
        (await register(api, phone=PHONE_PREFIX + "000001", business_name=BUSINESS_NAME)).json()[
            "access_token"
        ]
    )
    results = await _race(api, "POST", "/api/v1/categories", owner, {"name": "Drinks"})
    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.CREATED, HTTPStatus.CONFLICT, HTTPStatus.CONFLICT], statuses
    for r in results:
        if r.status_code == HTTPStatus.CONFLICT:
            assert r.json()["error"]["code"] == "CATEGORY_EXISTS"
            assert "uq_categories" not in r.text and "asyncpg" not in r.text
    async with engine.connect() as connection:
        count = await connection.scalar(
            text(
                "SELECT count(*) FROM categories WHERE business_id = "
                "(SELECT id FROM businesses WHERE name = :name)"
            ),
            {"name": BUSINESS_NAME},
        )
    assert count == 1


async def test_concurrent_product_creates_with_one_sku_yield_one_row(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = bearer(
        (await register(api, phone=PHONE_PREFIX + "000002", business_name=BUSINESS_NAME)).json()[
            "access_token"
        ]
    )
    # Distinct names so only the SKU index can clash; opening stock so the INITIAL movement
    # of each loser must roll back with its product.
    results: list[Response] = []

    async def attempt(i: int) -> None:
        async with _client(api, f"10.5.1.{i}") as client:
            results.append(
                await client.post(
                    "/api/v1/products",
                    headers=owner,
                    json={
                        "name": f"Item {i}",
                        "selling_price": "10",
                        "sku": "SKU-RACE",
                        "opening_stock": "1",
                        "opening_unit_cost": "1",
                    },
                )
            )

    async with anyio.create_task_group() as tg:
        for i in range(3):
            tg.start_soon(attempt, i)
    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.CREATED, HTTPStatus.CONFLICT, HTTPStatus.CONFLICT], statuses
    for r in results:
        if r.status_code == HTTPStatus.CONFLICT:
            assert r.json()["error"]["code"] == "SKU_EXISTS"
    async with engine.connect() as connection:
        business = "(SELECT id FROM businesses WHERE name = :name)"
        products = await connection.scalar(
            text(f"SELECT count(*) FROM products WHERE business_id IN {business}"),  # noqa: S608
            {"name": BUSINESS_NAME},
        )
        movements = await connection.scalar(
            text(f"SELECT count(*) FROM inventory_movements WHERE business_id IN {business}"),  # noqa: S608
            {"name": BUSINESS_NAME},
        )
    assert (products, movements) == (1, 1)


async def test_concurrent_product_creates_with_one_name_yield_one_row(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = bearer(
        (await register(api, phone=PHONE_PREFIX + "000003", business_name=BUSINESS_NAME)).json()[
            "access_token"
        ]
    )
    results = await _race(
        api, "POST", "/api/v1/products", owner, {"name": "Bread", "selling_price": "55"}
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.CREATED, HTTPStatus.CONFLICT, HTTPStatus.CONFLICT], statuses
    assert {r.json()["error"]["code"] for r in results if r.status_code == HTTPStatus.CONFLICT} == {
        "PRODUCT_NAME_EXISTS"
    }
