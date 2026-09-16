"""Racing sales: product row locks, customer row locks and the idempotency unique index.

Real commits on separate connections; rows are cleaned up afterwards.
"""

import uuid
from collections.abc import AsyncIterator
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
from tests.db.sales_helpers import SALES_URL, make_customer, make_product, sale_payload

pytestmark = [pytest.mark.db, pytest.mark.anyio]

PHONE_PREFIX = "+254702"
BUSINESS_NAME = "Sales Race Duka"


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
    api: AsyncClient,
    headers: dict[str, str],
    payloads: list[dict[str, object]],
    keys: list[str] | None = None,
) -> list[Response]:
    results: list[Response] = []

    async def attempt(i: int) -> None:
        async with _client(api, f"10.8.0.{i}") as client:
            key = keys[i] if keys else str(uuid.uuid4())
            results.append(
                await client.post(
                    SALES_URL, headers={**headers, "Idempotency-Key": key}, json=payloads[i]
                )
            )

    async with anyio.create_task_group() as tg:
        for i in range(len(payloads)):
            tg.start_soon(attempt, i)
    return results


async def _stock(engine: AsyncEngine, product_id: str) -> tuple[Decimal, Decimal, int]:
    """(cache, ledger sum, sale-movement count) — cache and ledger must agree."""
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT p.stock_quantity, "
                    "(SELECT coalesce(sum(quantity_delta), 0) FROM inventory_movements "
                    " WHERE product_id = p.id), "
                    "(SELECT count(*) FROM inventory_movements "
                    " WHERE product_id = p.id AND movement_type = 'SALE') "
                    "FROM products p WHERE p.id = :pid"
                ),
                {"pid": uuid.UUID(product_id)},
            )
        ).one()
    return Decimal(row[0]), Decimal(row[1]), int(row[2])


async def test_last_unit_goes_to_exactly_one_sale(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = await _owner(api, "000001")
    product = await make_product(api, owner, stock="1")
    payload = sale_payload([(product["id"], "1")], [("CASH", "500")])
    results = await _race(api, owner, [payload, payload])
    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.CREATED, HTTPStatus.CONFLICT], [r.text for r in results]
    loser = next(r for r in results if r.status_code == HTTPStatus.CONFLICT)
    assert loser.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    cache, ledger, sale_movements = await _stock(engine, product["id"])
    assert cache == ledger == Decimal("0.000") and sale_movements == 1
    async with engine.connect() as connection:
        sales = await connection.scalar(
            text(
                "SELECT count(*) FROM sales WHERE business_id = "
                "(SELECT id FROM businesses WHERE name = :n)"
            ),
            {"n": BUSINESS_NAME},
        )
    assert sales == 1


async def test_many_sales_of_a_scarce_product_never_oversell(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = await _owner(api, "000002")
    product = await make_product(api, owner, stock="5")
    payload = sale_payload([(product["id"], "2")], [("CASH", "1000")])
    results = await _race(api, owner, [payload] * 5)
    created = [r for r in results if r.status_code == HTTPStatus.CREATED]
    rejected = [r for r in results if r.status_code == HTTPStatus.CONFLICT]
    assert (len(created), len(rejected)) == (2, 3)  # 2 x 2 = 4 <= 5 < 3 x 2
    cache, ledger, sale_movements = await _stock(engine, product["id"])
    assert cache == ledger == Decimal("1.000") and sale_movements == 2


async def test_two_products_in_opposite_order_do_not_deadlock(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = await _owner(api, "000003")
    x = await make_product(api, owner, name="X", stock="10")
    y = await make_product(api, owner, name="Y", stock="10")
    forwards = sale_payload([(x["id"], "1"), (y["id"], "1")], [("CASH", "1000")])
    backwards = sale_payload([(y["id"], "1"), (x["id"], "1")], [("CASH", "1000")])
    results = await _race(api, owner, [forwards, backwards, forwards, backwards])
    assert all(r.status_code == HTTPStatus.CREATED for r in results), [r.text for r in results]
    assert (await _stock(engine, x["id"]))[0] == Decimal("6.000")
    assert (await _stock(engine, y["id"]))[0] == Decimal("6.000")


async def test_credit_limit_race_lets_only_what_fits_through(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = await _owner(api, "000004")
    product = await make_product(api, owner, stock="100")
    customer = await make_customer(api, owner, credit_limit="1000")
    payload = sale_payload([(product["id"], "1")], [("CREDIT", "500")], customer_id=customer["id"])
    results = await _race(api, owner, [payload] * 4)
    created = [r for r in results if r.status_code == HTTPStatus.CREATED]
    rejected = [r for r in results if r.status_code == HTTPStatus.CONFLICT]
    assert (len(created), len(rejected)) == (2, 2)  # 2 x 500 fill the limit exactly
    assert all(r.json()["error"]["code"] == "CREDIT_LIMIT_EXCEEDED" for r in rejected)
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT c.balance, (SELECT coalesce(sum(amount), 0) FROM credit_transactions "
                    "WHERE customer_id = c.id) FROM customers c WHERE c.id = :cid"
                ),
                {"cid": uuid.UUID(customer["id"])},
            )
        ).one()
    assert Decimal(row[0]) == Decimal(row[1]) == Decimal("1000.00")
    assert (await _stock(engine, product["id"]))[0] == Decimal("98.000")


async def test_concurrent_identical_requests_with_one_key_create_one_sale(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = await _owner(api, "000005")
    product = await make_product(api, owner, stock="10")
    customer = await make_customer(api, owner)
    key = str(uuid.uuid4())
    payload = sale_payload([(product["id"], "2")], [("CREDIT", "1000")], customer_id=customer["id"])
    results = await _race(api, owner, [payload] * 4, keys=[key] * 4)
    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.OK, HTTPStatus.OK, HTTPStatus.OK, HTTPStatus.CREATED], statuses
    assert len({r.json()["id"] for r in results}) == 1
    assert (await _stock(engine, product["id"])) == (Decimal("8.000"), Decimal("8.000"), 1)
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM sales WHERE idempotency_key = :k), "
                    "(SELECT count(*) FROM payments WHERE sale_id IN "
                    " (SELECT id FROM sales WHERE idempotency_key = :k)), "
                    "(SELECT count(*) FROM credit_transactions WHERE sale_id IN "
                    " (SELECT id FROM sales WHERE idempotency_key = :k)), "
                    "(SELECT balance FROM customers WHERE id = :cid)"
                ),
                {"k": uuid.UUID(key), "cid": uuid.UUID(customer["id"])},
            )
        ).one()
    assert tuple(row[:3]) == (1, 1, 1) and Decimal(row[3]) == Decimal("1000.00")


async def test_concurrent_different_payloads_with_one_key_keep_the_first_sale_intact(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = await _owner(api, "000006")
    product = await make_product(api, owner, stock="10")
    key = str(uuid.uuid4())
    payloads = [
        sale_payload([(product["id"], "1")], [("CASH", "500")]),
        sale_payload([(product["id"], "2")], [("CASH", "1000")]),
        sale_payload([(product["id"], "3")], [("CASH", "1500")]),
    ]
    results = await _race(api, owner, payloads, keys=[key] * 3)
    created = [r for r in results if r.status_code == HTTPStatus.CREATED]
    conflicts = [r for r in results if r.status_code == HTTPStatus.CONFLICT]
    assert (len(created), len(conflicts)) == (1, 2), [r.text for r in results]
    assert all(r.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT" for r in conflicts)
    winner = created[0].json()
    sold = Decimal(winner["items"][0]["quantity"])
    cache, ledger, sale_movements = await _stock(engine, product["id"])
    assert cache == ledger == Decimal("10.000") - sold and sale_movements == 1
