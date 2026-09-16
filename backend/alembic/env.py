"""Alembic environment for the async SQLAlchemy engine.

The URL comes from `sqlalchemy.url` when a caller set it programmatically (tests),
otherwise from `DATABASE_URL` through the application settings. Migrations run
through the async engine with `run_sync`, matching how the application connects.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from app.core.config import get_settings
from app.models import Base
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: the test suite runs migrations in-process, and the
    # default would silently switch off every `app.*` logger created before this point.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    return str(get_settings().database_url)


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a database connection (`alembic upgrade head --sql`)."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
