"""Racing membership changes cannot leave a business ownerless (DATA_MAPPING §3.3).

Real commits on separate connections; rows are cleaned up afterwards (same pattern as
`test_auth_concurrency.py`).
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

from tests.db.auth_helpers import PASSWORD, bearer, login, register
from tests.db.conftest import TEST_BASE_URL

pytestmark = [pytest.mark.db, pytest.mark.anyio]

PHONE_PREFIX = "+254708"
BUSINESS_NAME = "Race Duka"
USERS_URL = "/api/v1/users"


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
            users = "(SELECT id FROM users WHERE phone LIKE :prefix)"
            for table in ("audit_logs", "refresh_tokens", "business_memberships"):
                column = "actor_user_id" if table == "audit_logs" else "user_id"
                await connection.execute(
                    text(f"DELETE FROM {table} WHERE {column} IN {users}"),  # noqa: S608 — constants
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


def _client(api: AsyncClient, ip: str) -> AsyncClient:
    transport = api._transport
    assert isinstance(transport, ASGITransport)
    return AsyncClient(
        transport=ASGITransport(app=transport.app, client=(ip, 40000)), base_url=TEST_BASE_URL
    )


async def _two_owner_business(api: AsyncClient) -> tuple[dict[str, str], str, dict[str, str], str]:
    """Returns (owner1 headers, owner1 id, owner2 headers, owner2 id)."""
    first = await register(api, phone=PHONE_PREFIX + "100001", business_name=BUSINESS_NAME)
    assert first.status_code == HTTPStatus.CREATED, first.text
    owner1 = bearer(first.json()["access_token"])
    created = await api.post(
        USERS_URL,
        headers=owner1,
        json={"full_name": "Second", "phone": PHONE_PREFIX + "100002", "password": PASSWORD},
    )
    assert created.status_code == HTTPStatus.CREATED, created.text
    second_id = created.json()["user_id"]
    promoted = await api.patch(f"{USERS_URL}/{second_id}", headers=owner1, json={"role": "OWNER"})
    assert promoted.status_code == HTTPStatus.OK, promoted.text
    # The second owner must clear must_change_password before acting.
    session = await login(api, PHONE_PREFIX + "100002")
    changed = await api.post(
        "/api/v1/auth/change-password",
        headers=bearer(session.json()["access_token"]),
        json={"current_password": PASSWORD, "new_password": PASSWORD + " changed"},
    )
    assert changed.status_code == HTTPStatus.OK, changed.text
    owner2 = bearer(changed.json()["access_token"])
    api.cookies.clear()
    return owner1, first.json()["user"]["id"], owner2, second_id


async def test_concurrent_step_downs_leave_exactly_one_owner(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner1, owner1_id, owner2, owner2_id = await _two_owner_business(api)
    results: list[Response] = []

    async def step_down(headers: dict[str, str], user_id: str, ip: str) -> None:
        async with _client(api, ip) as client:
            results.append(
                await client.patch(
                    f"{USERS_URL}/{user_id}", headers=headers, json={"role": "STAFF"}
                )
            )

    # Each owner demotes themselves at the same moment; without the row lock both would
    # see "another owner exists" and succeed.
    async with anyio.create_task_group() as tg:
        tg.start_soon(step_down, owner1, owner1_id, "10.3.0.1")
        tg.start_soon(step_down, owner2, owner2_id, "10.3.0.2")

    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.OK, HTTPStatus.CONFLICT], [r.text for r in results]
    loser = next(r for r in results if r.status_code == HTTPStatus.CONFLICT)
    assert loser.json()["error"]["code"] == "LAST_OWNER"

    async with engine.connect() as connection:
        owners = await connection.scalar(
            text(
                "SELECT count(*) FROM business_memberships m JOIN users u ON u.id = m.user_id "
                "WHERE u.phone LIKE :prefix AND m.role = 'OWNER' AND m.is_active"
            ),
            {"prefix": PHONE_PREFIX + "%"},
        )
    assert owners == 1


async def test_concurrent_deactivations_of_both_owners_keep_one_active(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner1, owner1_id, owner2, owner2_id = await _two_owner_business(api)
    results: list[Response] = []

    async def deactivate_other(headers: dict[str, str], target: str, ip: str) -> None:
        async with _client(api, ip) as client:
            results.append(
                await client.patch(
                    f"{USERS_URL}/{target}", headers=headers, json={"is_active": False}
                )
            )

    async with anyio.create_task_group() as tg:
        tg.start_soon(deactivate_other, owner1, owner2_id, "10.3.1.1")
        tg.start_soon(deactivate_other, owner2, owner1_id, "10.3.1.2")

    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.OK, HTTPStatus.CONFLICT], [r.text for r in results]
    async with engine.connect() as connection:
        owners = await connection.scalar(
            text(
                "SELECT count(*) FROM business_memberships m JOIN users u ON u.id = m.user_id "
                "WHERE u.phone LIKE :prefix AND m.role = 'OWNER' AND m.is_active"
            ),
            {"prefix": PHONE_PREFIX + "%"},
        )
    assert owners == 1


async def test_concurrent_staff_creation_with_one_phone_creates_one_user(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    first = await register(api, phone=PHONE_PREFIX + "200001", business_name=BUSINESS_NAME)
    owner = bearer(first.json()["access_token"])
    phone = PHONE_PREFIX + "200002"
    results: list[Response] = []

    async def create(ip: str) -> None:
        async with _client(api, ip) as client:
            results.append(
                await client.post(
                    USERS_URL,
                    headers=owner,
                    json={"full_name": "Dup", "phone": phone, "password": PASSWORD},
                )
            )

    async with anyio.create_task_group() as tg:
        for i in range(3):
            tg.start_soon(create, f"10.3.2.{i}")

    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.CREATED, HTTPStatus.CONFLICT, HTTPStatus.CONFLICT], statuses
    async with engine.connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM users WHERE phone = :phone"), {"phone": phone}
        )
        audits = await connection.scalar(
            text(
                "SELECT count(*) FROM audit_logs WHERE action = 'user.create' AND entity_id IN "
                "(SELECT id FROM users WHERE phone = :phone)"
            ),
            {"phone": phone},
        )
    assert count == 1
    assert audits == 1  # the losers' audit rows rolled back with their users
