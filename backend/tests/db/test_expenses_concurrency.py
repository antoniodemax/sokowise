"""Racing expense writes (real commits, separate connections)."""

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

pytestmark = [pytest.mark.db, pytest.mark.anyio]

PHONE_PREFIX = "+254710"
BUSINESS_NAME = "Expense Race Duka"
URL = "/api/v1/expenses"


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
            for table in ("expenses", "audit_logs"):
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


async def test_concurrent_creates_all_land_and_total_correctly(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = await _owner(api, "000001")
    results: list[Response] = []

    async def attempt(i: int) -> None:
        async with _client(api, f"10.10.0.{i}") as client:
            results.append(
                await client.post(
                    URL,
                    headers=owner,
                    json={"amount": "12.50", "category": f"cat {i % 2}", "payment_method": "CASH"},
                )
            )

    async with anyio.create_task_group() as tg:
        for i in range(8):
            tg.start_soon(attempt, i)
    assert all(r.status_code == HTTPStatus.CREATED for r in results)
    assert len({r.json()["id"] for r in results}) == 8
    breakdown = (
        await api.get("/api/v1/analytics/expenses", headers=owner, params={"period": "today"})
    ).json()
    assert (breakdown["total"], breakdown["count"]) == ("100.00", 8)
    assert [(g["key"], g["count"]) for g in breakdown["by_category"]] == [
        ("CAT 0", 4),
        ("CAT 1", 4),
    ]


async def test_concurrent_update_and_delete_leave_a_consistent_row(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = await _owner(api, "000002")
    created = await api.post(
        URL, headers=owner, json={"amount": "100", "category": "RENT", "payment_method": "CASH"}
    )
    expense_id = created.json()["id"]
    results: dict[str, Response] = {}

    async def patch() -> None:
        async with _client(api, "10.10.1.1") as client:
            results["patch"] = await client.patch(
                f"{URL}/{expense_id}", headers=owner, json={"amount": "150"}
            )

    async def delete() -> None:
        async with _client(api, "10.10.1.2") as client:
            results["delete"] = await client.delete(f"{URL}/{expense_id}", headers=owner)

    async with anyio.create_task_group() as tg:
        tg.start_soon(patch)
        tg.start_soon(delete)

    assert results["delete"].status_code == HTTPStatus.NO_CONTENT
    # The row lock serialises them: either the edit landed first (then was deleted) or the
    # delete won and the edit was refused. Never a half state.
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text("SELECT amount, deleted_at IS NOT NULL FROM expenses WHERE id = :id"),
                {"id": uuid.UUID(expense_id)},
            )
        ).one()
    assert row[1] is True
    if results["patch"].status_code == HTTPStatus.OK:
        assert Decimal(row[0]) == Decimal("150.00")
    else:
        assert results["patch"].status_code == HTTPStatus.CONFLICT
        assert results["patch"].json()["error"]["code"] == "EXPENSE_DELETED"
        assert Decimal(row[0]) == Decimal("100.00")
    async with engine.connect() as connection:
        audits = await connection.scalar(
            text("SELECT count(*) FROM audit_logs WHERE entity_id = :id"),
            {"id": uuid.UUID(expense_id)},
        )
    assert audits == (2 if results["patch"].status_code == HTTPStatus.OK else 1)
