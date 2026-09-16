"""Async engine and session factory (docs/ARCHITECTURE.md §3.4, §3.5).

The engine is created once per process in the application lifespan and stored on
`app.state`; routes obtain a session through `get_session`. Services own
transactions (`async with transaction(session)`); `get_session` itself never commits.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        str(settings.database_url),
        pool_pre_ping=True,
        # Fail fast on an unreachable database instead of hanging a request.
        connect_args={"timeout": 5},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: attributes stay usable after commit without an implicit
    # refresh, which would be a hidden await (MissingGreenlet) in async code.
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, closed when the request ends."""
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


@asynccontextmanager
async def transaction(session: AsyncSession) -> AsyncIterator[None]:
    """Commit on success, roll back on any exception.

    Services wrap their work in this instead of `session.begin()` because a request
    dependency (`get_current_user`) usually ran a read first, which autobegan the
    session's transaction; `begin()` would then raise. Joining it is what we want:
    one transaction per request, committed exactly once by the service.
    """
    try:
        yield
    except BaseException:
        await session.rollback()
        raise
    else:
        await session.commit()
