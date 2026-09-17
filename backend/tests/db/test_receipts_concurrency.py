"""Two simultaneous confirmations of one receipt create exactly one set of movements.

Real commits on separate connections (the receipt row lock is what serialises them);
rows are cleaned up afterwards.
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
from tests.db.receipt_helpers import (
    FakeReceiptExtractionProvider,
    confirm,
    extraction,
    line,
    process,
    upload_ok,
)
from tests.db.sales_helpers import make_product

pytestmark = [pytest.mark.db, pytest.mark.anyio]

PHONE_PREFIX = "+254706"
BUSINESS_NAME = "Receipt Race Duka"


@pytest.fixture
async def committed_api(engine: AsyncEngine, tmp_path: object) -> AsyncIterator[AsyncClient]:
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    get_settings.cache_clear()
    app = create_app(Settings(receipt_storage_dir=str(tmp_path)))
    provider = FakeReceiptExtractionProvider([extraction([line("Sukari 1kg", "5", "135")])])
    from app.api.v1.receipts import get_receipt_provider

    app.dependency_overrides[get_receipt_provider] = lambda: provider

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
                "receipt_lines",
                "receipts",
                "inventory_movements",
                "audit_logs",
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


async def test_concurrent_confirmations_apply_the_receipt_once(
    committed_api: AsyncClient, engine: AsyncEngine
) -> None:
    api = committed_api
    owner = bearer(
        (await register(api, phone=PHONE_PREFIX + "000001", business_name=BUSINESS_NAME)).json()[
            "access_token"
        ]
    )
    sugar = await make_product(api, owner, name="Sukari 1kg", price="160", cost="135", stock="10")
    receipt = await upload_ok(api, owner)
    ready = await process(api, owner, receipt["id"])
    assert ready.status_code == HTTPStatus.OK, ready.text
    line_id = ready.json()["lines"][0]["id"]
    decisions = [
        {"line_id": line_id, "product_id": sugar["id"], "quantity": "5", "unit_cost": "135"}
    ]

    transport = api._transport
    assert isinstance(transport, ASGITransport)
    results: list[Response] = []

    async def attempt(ip: str) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=transport.app, client=(ip, 40000)), base_url=TEST_BASE_URL
        ) as client:
            results.append(await confirm(client, owner, receipt["id"], decisions))

    async with anyio.create_task_group() as tg:
        for i in range(4):
            tg.start_soon(attempt, f"10.7.0.{i}")

    statuses = sorted(r.status_code for r in results)
    assert statuses == [HTTPStatus.OK] + [HTTPStatus.CONFLICT] * 3, statuses
    async with engine.connect() as connection:
        restocks = await connection.scalar(
            text(
                "SELECT count(*) FROM inventory_movements WHERE movement_type = 'RESTOCK' AND "
                "business_id = (SELECT id FROM businesses WHERE name = :name)"
            ),
            {"name": BUSINESS_NAME},
        )
        stock = await connection.scalar(
            text("SELECT stock_quantity FROM products WHERE id = :id"), {"id": sugar["id"]}
        )
    assert (restocks, str(stock)) == (1, "15.000")
