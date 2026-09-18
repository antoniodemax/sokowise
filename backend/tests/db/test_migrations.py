"""Alembic migrations against a real PostgreSQL 16."""

import anyio
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.models import Base
from sqlalchemy import Connection, inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.db.conftest import alembic_config

pytestmark = [pytest.mark.db, pytest.mark.anyio]

EXPECTED_TABLES = {
    "businesses",
    "users",
    "business_memberships",
    "refresh_tokens",
    "categories",
    "products",
    "inventory_movements",
    "customers",
    "sales",
    "sale_items",
    "payments",
    "credit_transactions",
    "expenses",
    "ai_conversations",
    "ai_messages",
    "receipts",
    "receipt_lines",
    "mpesa_messages",
    "password_reset_codes",
    "audit_logs",
}


def _table_names(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())


async def test_engine_connects(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        version = (await connection.execute(text("SHOW server_version"))).scalar_one()
    assert version.startswith("16")


async def test_all_sixteen_tables_exist_after_upgrade(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        tables = await connection.run_sync(_table_names)
    assert tables - {"alembic_version"} == EXPECTED_TABLES
    assert len(EXPECTED_TABLES) == 20


async def test_models_match_migrations_exactly(engine: AsyncEngine) -> None:
    """Autogenerate must see no drift between Base.metadata and the migrated schema."""

    def diff(connection: Connection) -> list[object]:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return list(compare_metadata(context, Base.metadata))

    async with engine.connect() as connection:
        drift = await connection.run_sync(diff)
    assert drift == [], f"schema drift: {drift}"


async def test_downgrade_to_base_and_upgrade_from_scratch(
    engine: AsyncEngine, migrated_database: str
) -> None:
    """The schema is fully reversible and reproducible from an empty database."""
    config = alembic_config(migrated_database)
    await engine.dispose()  # release this test's connections before DDL runs

    # Alembic drives its own event loop (asyncio.run), so it must run off the test loop.
    await anyio.to_thread.run_sync(command.downgrade, config, "base")
    async with engine.connect() as connection:
        after_downgrade = await connection.run_sync(_table_names)
    await engine.dispose()
    assert after_downgrade - {"alembic_version"} == set()

    await anyio.to_thread.run_sync(command.upgrade, config, "head")
    async with engine.connect() as connection:
        after_upgrade = await connection.run_sync(_table_names)
    assert after_upgrade - {"alembic_version"} == EXPECTED_TABLES
