"""Simultaneous pastes of one SMS create one row (partial unique index + replay)."""

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
BUSINESS_NAME = "Mpesa Race Duka"
SMS = (
    "RK1RACE001 Confirmed. You have received Ksh1,000.00 from RACE TESTER 0712***456 "
    "on 18/9/26 at 2:15 PM. New business balance is Ksh5,000.00."
)


@pytest.fixture
async def committed_api(engine: AsyncEngine, tmp_path: object) -> AsyncIterator[AsyncClient]:
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    get_settings.cache_clear()
    app = create_app(Settings(receipt_storage_dir=str(tmp_path)))

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
            for table in ("mpesa_messages", "audit_logs"):
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
            await connection.execute(text(f"DELETE FROM businesses WHERE id IN {business}"), params)  # noqa: S608
            await connection.execute(text(f"DELETE FROM users WHERE id IN {users}"), params)  # noqa: S608


async def test_concurrent_pastes_of_one_sms_store_it_once(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    registered = await register(
        committed_api, business_name=BUSINESS_NAME, phone=PHONE_PREFIX + "000101"
    )
    assert registered.status_code == HTTPStatus.CREATED, registered.text
    headers = bearer(registered.json()["access_token"])
    responses: list[Response] = []

    async def go() -> None:
        responses.append(
            await committed_api.post("/api/v1/mpesa/messages", headers=headers, json={"text": SMS})
        )

    async with anyio.create_task_group() as tg:
        for _ in range(4):
            tg.start_soon(go)

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [HTTPStatus.OK, HTTPStatus.OK, HTTPStatus.OK, HTTPStatus.CREATED], statuses
    assert len({r.json()["id"] for r in responses}) == 1
    async with engine.connect() as connection:
        rows = await connection.scalar(
            text(
                "SELECT count(*) FROM mpesa_messages WHERE business_id = "
                "(SELECT id FROM businesses WHERE name = :name)"
            ),
            {"name": BUSINESS_NAME},
        )
        audits = await connection.scalar(
            text(
                "SELECT count(*) FROM audit_logs WHERE action = 'mpesa.paste' AND business_id = "
                "(SELECT id FROM businesses WHERE name = :name)"
            ),
            {"name": BUSINESS_NAME},
        )
    assert rows == 1 and audits == 1
