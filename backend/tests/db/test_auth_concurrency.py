"""Two concurrent refreshes with the same token: exactly one wins (ARCHITECTURE §3.4).

These tests need real commits on separate connections, so they bypass the
rolled-back `db_session` and clean up their own rows afterwards.
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

from tests.db.auth_helpers import (
    CSRF_HEADERS,
    REFRESH_URL,
    refresh,
    refresh_cookie,
    register,
    set_refresh_cookie,
)
from tests.db.conftest import TEST_BASE_URL

pytestmark = [pytest.mark.db, pytest.mark.anyio]

# Rows created here are committed; this phone prefix marks them for cleanup.
PHONE_PREFIX = "+254709"
BUSINESS_NAME = "Concurrency Duka"


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
            params = {"prefix": PHONE_PREFIX + "%", "name": BUSINESS_NAME}
            await connection.execute(
                text(
                    "DELETE FROM refresh_tokens WHERE user_id IN "
                    "(SELECT id FROM users WHERE phone LIKE :prefix)"
                ),
                params,
            )
            await connection.execute(
                text(
                    "DELETE FROM business_memberships WHERE user_id IN "
                    "(SELECT id FROM users WHERE phone LIKE :prefix)"
                ),
                params,
            )
            await connection.execute(
                text(
                    "DELETE FROM businesses WHERE name = :name AND id NOT IN "
                    "(SELECT business_id FROM business_memberships)"
                ),
                params,
            )
            await connection.execute(text("DELETE FROM users WHERE phone LIKE :prefix"), params)
        get_settings.cache_clear()


async def test_concurrent_refreshes_with_the_same_token_let_exactly_one_through(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    registered = await register(api, phone=PHONE_PREFIX + "000001", business_name=BUSINESS_NAME)
    assert registered.status_code == HTTPStatus.CREATED
    token = refresh_cookie(api)
    assert token is not None
    user_id = registered.json()["user"]["id"]

    transport = api._transport
    assert isinstance(transport, ASGITransport)
    results: list[Response] = []

    async def attempt(ip: str) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=transport.app, client=(ip, 40000)), base_url=TEST_BASE_URL
        ) as client:
            set_refresh_cookie(client, token)
            results.append(await client.post(REFRESH_URL, headers=CSRF_HEADERS))

    async with anyio.create_task_group() as tg:
        tg.start_soon(attempt, "10.1.0.1")
        tg.start_soon(attempt, "10.1.0.2")

    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.OK, HTTPStatus.UNAUTHORIZED], statuses

    # The loser's replay revoked the family, including the winner's brand-new token.
    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "SELECT family_id, revoked_at IS NOT NULL AS revoked FROM refresh_tokens "
                    "WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
        ).all()
    assert len(rows) == 2
    assert len({row.family_id for row in rows}) == 1
    assert all(row.revoked for row in rows)
    winner = next(r for r in results if r.status_code == HTTPStatus.OK)
    new_token = winner.cookies.get("sokowise_refresh")
    assert new_token is not None and new_token != token
    set_refresh_cookie(api, new_token)
    assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED


async def test_concurrent_registrations_with_one_phone_create_one_account(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    """The unique constraint, not an application check, decides the race."""
    api = committed_api
    transport = api._transport
    assert isinstance(transport, ASGITransport)
    phone = PHONE_PREFIX + "000002"
    results: list[Response] = []

    async def attempt(ip: str) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=transport.app, client=(ip, 40000)), base_url=TEST_BASE_URL
        ) as client:
            results.append(await register(client, phone=phone, business_name=BUSINESS_NAME))

    async with anyio.create_task_group() as tg:
        for i in range(3):
            tg.start_soon(attempt, f"10.2.0.{i}")

    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.CREATED, HTTPStatus.CONFLICT, HTTPStatus.CONFLICT], statuses
    async with engine.connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM businesses WHERE name = :name"), {"name": BUSINESS_NAME}
        )
    assert count == 1  # the losers' businesses were rolled back with their users
