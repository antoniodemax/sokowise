"""Racing restocks/adjustments and posting-order guarantees (real commits, separate connections)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
from tests.db.sales_helpers import make_product, sale_payload, sell

pytestmark = [pytest.mark.db, pytest.mark.anyio]

PHONE_PREFIX = "+254700"
BUSINESS_NAME = "Inventory Race Duka"
URL = "/api/v1/inventory"


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
            for table in (
                "credit_transactions",
                "inventory_movements",
                "payments",
                "sale_items",
                "sales",
                "audit_logs",
                "customers",
                "products",
                "categories",
            ):
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


async def _owner(api: AsyncClient, suffix: str) -> dict[str, str]:
    response = await register(api, phone=PHONE_PREFIX + suffix, business_name=BUSINESS_NAME)
    assert response.status_code == HTTPStatus.CREATED, response.text
    return bearer(response.json()["access_token"])


async def _race(
    api: AsyncClient, headers: dict[str, str], path: str, bodies: list[dict[str, object]]
) -> list[Response]:
    results: list[Response] = []

    async def attempt(i: int) -> None:
        async with _client(api, f"10.9.0.{i}") as client:
            results.append(await client.post(path, headers=headers, json=bodies[i]))

    async with anyio.create_task_group() as tg:
        for i in range(len(bodies)):
            tg.start_soon(attempt, i)
    return results


async def _stock(engine: AsyncEngine, product_id: str) -> tuple[Decimal, Decimal]:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT p.stock_quantity, (SELECT coalesce(sum(quantity_delta), 0) "
                    "FROM inventory_movements WHERE product_id = p.id) "
                    "FROM products p WHERE p.id = :pid"
                ),
                {"pid": uuid.UUID(product_id)},
            )
        ).one()
    return Decimal(row[0]), Decimal(row[1])


async def test_concurrent_restocks_all_land_and_the_cache_equals_the_ledger(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = await _owner(api, "100001")
    product = await make_product(api, owner, stock="10")
    body: dict[str, object] = {"product_id": product["id"], "quantity": "3", "unit_cost": "1"}
    results = await _race(api, owner, f"{URL}/restock", [body] * 6)
    assert all(r.status_code == HTTPStatus.CREATED for r in results), [r.text for r in results]
    # Every quantity_after is distinct: the row lock serialised the six writes.
    assert sorted(Decimal(r.json()["quantity_after"]) for r in results) == [
        Decimal(n) for n in (13, 16, 19, 22, 25, 28)
    ]
    cache, ledger = await _stock(engine, product["id"])
    assert cache == ledger == Decimal("28.000")


async def test_concurrent_negative_adjustments_never_go_below_zero(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = await _owner(api, "100002")
    product = await make_product(api, owner, stock="5")
    body: dict[str, object] = {
        "product_id": product["id"],
        "quantity_delta": "-2",
        "reason": "damage",
    }
    results = await _race(api, owner, f"{URL}/adjust", [body] * 4)
    created = [r for r in results if r.status_code == HTTPStatus.CREATED]
    rejected = [r for r in results if r.status_code == HTTPStatus.CONFLICT]
    assert (len(created), len(rejected)) == (2, 2)  # 2 x 2 = 4 <= 5 < 3 x 2
    assert all(r.json()["error"]["code"] == "INSUFFICIENT_STOCK" for r in rejected)
    cache, ledger = await _stock(engine, product["id"])
    assert cache == ledger == Decimal("1.000")


async def test_restock_and_sale_race_keep_the_ledger_consistent(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = await _owner(api, "100003")
    product = await make_product(api, owner, stock="1")
    results: list[Response] = []

    async def restock_it() -> None:
        async with _client(api, "10.9.1.1") as client:
            results.append(
                await client.post(
                    f"{URL}/restock",
                    headers=owner,
                    json={"product_id": product["id"], "quantity": "1", "unit_cost": "1"},
                )
            )

    async def sell_two() -> None:
        async with _client(api, "10.9.1.2") as client:
            results.append(
                await client.post(
                    "/api/v1/sales",
                    headers={**owner, "Idempotency-Key": str(uuid.uuid4())},
                    json=sale_payload([(product["id"], "2")], [("CASH", "1000")]),
                )
            )

    async with anyio.create_task_group() as tg:
        tg.start_soon(restock_it)
        tg.start_soon(sell_two)
    statuses = sorted(r.status_code for r in results)
    # Either the restock landed first (sale of 2 succeeds → 0) or the sale was refused (→ 2).
    cache, ledger = await _stock(engine, product["id"])
    assert cache == ledger
    assert (statuses, cache) in (
        ([HTTPStatus.CREATED, HTTPStatus.CREATED], Decimal("0.000")),
        ([HTTPStatus.CREATED, HTTPStatus.CONFLICT], Decimal("2.000")),
    )


async def test_history_is_in_posting_order_and_quantity_after_ignores_backdating(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = await _owner(api, "100004")
    product = await make_product(api, owner, stock="10")
    assert (
        await api.post(
            f"{URL}/restock",
            headers=owner,
            json={"product_id": product["id"], "quantity": "5", "unit_cost": "1"},
        )
    ).status_code == 201  # 15
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    await sell(
        api, owner, sale_payload([(product["id"], "4")], [("CASH", "2000")], sold_at=yesterday)
    )  # 11, backdated
    assert (
        await api.post(
            f"{URL}/adjust",
            headers=owner,
            json={"product_id": product["id"], "quantity_delta": "-1", "reason": "x"},
        )
    ).status_code == 201  # 10
    rows = (
        await api.get(f"{URL}/movements", headers=owner, params={"product_id": product["id"]})
    ).json()
    assert [(m["movement_type"], m["quantity_after"]) for m in rows] == [
        ("ADJUSTMENT", "10.000"),
        ("SALE", "11.000"),
        ("RESTOCK", "15.000"),
        ("INITIAL", "10.000"),
    ]
    assert rows[1]["occurred_at"] < rows[2]["occurred_at"]  # earlier business time, later posting
    assert (
        rows[0]["created_at"]
        > rows[1]["created_at"]
        > rows[2]["created_at"]
        > rows[3]["created_at"]
    )
    cache, ledger = await _stock(engine, product["id"])
    assert cache == ledger == Decimal("10.000")
