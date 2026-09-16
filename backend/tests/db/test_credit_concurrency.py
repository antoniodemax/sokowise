"""Racing ledger writes: the customer row lock serialises them (DATA_MAPPING §3.12).

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
from tests.db.credit_helpers import CUSTOMERS_URL, create_customer

pytestmark = [pytest.mark.db, pytest.mark.anyio]

PHONE_PREFIX = "+254704"
BUSINESS_NAME = "Credit Race Duka"


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
            for table in ("credit_transactions", "audit_logs", "customers"):
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


async def _owner_with_debtor(
    api: AsyncClient, engine: AsyncEngine, suffix: str, debt: str
) -> tuple[dict[str, str], str]:
    owner = bearer(
        (await register(api, phone=PHONE_PREFIX + suffix, business_name=BUSINESS_NAME)).json()[
            "access_token"
        ]
    )
    cid = (await create_customer(api, owner, name="Debtor " + suffix))["id"]
    # Seed the debt through the owner adjustment endpoint (the Phase 7 write path).
    seeded = await api.post(
        f"{CUSTOMERS_URL}/{cid}/adjustments",
        headers=owner,
        json={"amount": debt, "direction": "INCREASE", "reason": "opening balance"},
    )
    assert seeded.status_code == HTTPStatus.CREATED, seeded.text
    return owner, cid


async def _state(engine: AsyncEngine, cid: str) -> tuple[Decimal, Decimal, int]:
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT c.balance, "
                    "(SELECT coalesce(sum(amount), 0) FROM credit_transactions "
                    " WHERE customer_id = c.id), "
                    "(SELECT count(*) FROM credit_transactions WHERE customer_id = c.id) "
                    "FROM customers c WHERE c.id = :cid"
                ),
                {"cid": uuid.UUID(cid)},
            )
        ).one()
    return Decimal(row[0]), Decimal(row[1]), int(row[2])


async def test_two_concurrent_800_repayments_against_1000_let_exactly_one_through(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner, cid = await _owner_with_debtor(api, engine, "000001", "1000")
    results: list[Response] = []

    async def attempt(ip: str) -> None:
        async with _client(api, ip) as client:
            results.append(
                await client.post(
                    f"{CUSTOMERS_URL}/{cid}/repayments",
                    headers=owner,
                    json={"amount": "800", "payment_method": "CASH"},
                )
            )

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt, "10.7.0.1")
        tg.start_soon(attempt, "10.7.0.2")

    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.CREATED, HTTPStatus.CONFLICT], [r.text for r in results]
    loser = next(r for r in results if r.status_code == HTTPStatus.CONFLICT)
    assert loser.json()["error"]["code"] == "REPAYMENT_EXCEEDS_BALANCE"
    balance, ledger_sum, entries = await _state(engine, cid)
    assert balance == ledger_sum == Decimal("200.00")
    assert entries == 2  # opening adjustment + one repayment


async def test_many_concurrent_small_repayments_never_overshoot(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner, cid = await _owner_with_debtor(api, engine, "000002", "500")
    results: list[Response] = []

    async def attempt(i: int) -> None:
        async with _client(api, f"10.7.1.{i}") as client:
            results.append(
                await client.post(
                    f"{CUSTOMERS_URL}/{cid}/repayments",
                    headers=owner,
                    json={"amount": "150", "payment_method": "MPESA", "reference": f"R{i}"},
                )
            )

    async with anyio.create_task_group() as tg:
        for i in range(6):
            tg.start_soon(attempt, i)

    created = [r for r in results if r.status_code == HTTPStatus.CREATED]
    rejected = [r for r in results if r.status_code == HTTPStatus.CONFLICT]
    assert (len(created), len(rejected)) == (3, 3)  # 3 x 150 = 450 <= 500 < 4 x 150
    assert sorted(r.json()["balance_after"] for r in created) == ["200.00", "350.00", "50.00"]
    balance, ledger_sum, entries = await _state(engine, cid)
    assert balance == ledger_sum == Decimal("50.00")
    assert entries == 4


async def test_concurrent_retries_with_one_idempotency_key_post_once(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner, cid = await _owner_with_debtor(api, engine, "000003", "1000")
    key = str(uuid.uuid4())
    results: list[Response] = []

    async def attempt(i: int) -> None:
        async with _client(api, f"10.7.2.{i}") as client:
            results.append(
                await client.post(
                    f"{CUSTOMERS_URL}/{cid}/repayments",
                    headers={**owner, "Idempotency-Key": key},
                    json={"amount": "300", "payment_method": "CASH"},
                )
            )

    async with anyio.create_task_group() as tg:
        for i in range(4):
            tg.start_soon(attempt, i)

    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.OK, HTTPStatus.OK, HTTPStatus.OK, HTTPStatus.CREATED], statuses
    assert len({r.json()["id"] for r in results}) == 1  # everyone got the same entry
    balance, ledger_sum, entries = await _state(engine, cid)
    assert balance == ledger_sum == Decimal("700.00")
    assert entries == 2


async def test_concurrent_adjustments_serialise_on_the_customer_row(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner, cid = await _owner_with_debtor(api, engine, "000004", "100")
    results: list[Response] = []

    async def attempt(i: int, direction: str) -> None:
        async with _client(api, f"10.7.3.{i}") as client:
            results.append(
                await client.post(
                    f"{CUSTOMERS_URL}/{cid}/adjustments",
                    headers=owner,
                    json={"amount": "60", "direction": direction, "reason": f"r{i}"},
                )
            )

    # Two decreases of 60 against 100: exactly one may succeed; the increase always does.
    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt, 0, "DECREASE")
        tg.start_soon(attempt, 1, "DECREASE")
        tg.start_soon(attempt, 2, "INCREASE")

    created = sorted(r.json()["amount"] for r in results if r.status_code == HTTPStatus.CREATED)
    rejected = [r for r in results if r.status_code == HTTPStatus.CONFLICT]
    balance, ledger_sum, _ = await _state(engine, cid)
    assert balance == ledger_sum >= 0
    # Either both decreases fit (if the increase landed first) or exactly one did.
    assert created in (["-60.00", "-60.00", "60.00"], ["-60.00", "60.00"])
    assert len(rejected) == 3 - len(created)
    assert all(r.json()["error"]["code"] == "ADJUSTMENT_EXCEEDS_BALANCE" for r in rejected)
