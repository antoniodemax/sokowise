"""PostgreSQL fixtures. Every test here is marked `db` and needs TEST_DATABASE_URL.

Session start: `alembic upgrade head` on the test database. Each test then runs
inside an outer transaction that is rolled back, so tests never see each other's rows.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import TEST_DATABASE_URL

# A host with a dot: http.cookiejar treats a dotless host as "<host>.local", which
# makes cookies set explicitly by tests (attacker replays) fail to match.
TEST_BASE_URL = "https://api.sokowise.test"
ApiFactory = Callable[..., Awaitable[AsyncClient]]

pytestmark = pytest.mark.db

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def alembic_config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture(scope="session")
def database_url() -> str:
    assert TEST_DATABASE_URL, "TEST_DATABASE_URL must be set for database tests"
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    """Bring the test database to `head` from whatever state it was left in."""
    command.upgrade(alembic_config(database_url), "head")
    return database_url


@pytest.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    # NullPool: asyncpg connections are bound to the event loop of the test that made them.
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session inside an outer transaction that is always rolled back."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


# --- API tests (Phase 3+) -----------------------------------------------------------
#
# `api_factory` builds an application whose request sessions are the test's own
# `db_session`, so every request runs inside the rolled-back outer transaction and the
# test can also inspect or edit rows directly. Requests go through httpx's ASGI
# transport in the test's event loop (asyncpg connections are loop-bound). The base
# URL is https so the `Secure` refresh cookie is stored and sent by the cookie jar.


@pytest.fixture
async def api_factory(db_session: AsyncSession) -> AsyncIterator[ApiFactory]:
    async with AsyncExitStack() as stack:

        async def make(**overrides: object) -> AsyncClient:
            get_settings.cache_clear()
            app = create_app(Settings(**overrides))  # type: ignore[arg-type]

            async def _test_session() -> AsyncIterator[AsyncSession]:
                yield db_session

            app.dependency_overrides[get_session] = _test_session
            client = AsyncClient(transport=ASGITransport(app=app), base_url=TEST_BASE_URL)
            return await stack.enter_async_context(client)

        yield make
        get_settings.cache_clear()


@pytest.fixture
async def api(api_factory: ApiFactory) -> AsyncClient:
    return await api_factory()
