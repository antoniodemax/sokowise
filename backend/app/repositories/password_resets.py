"""password_reset_codes (docs/DATA_MAPPING.md §3.20).

Only hashes are stored. `consume` is the single atomic step of a successful reset: it
marks the live code used and returns it in one UPDATE, so two concurrent confirms with
the same code cannot both succeed. A wrong guess is counted with `count_attempt`.
"""

import uuid
from datetime import datetime

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PasswordResetCode

MAX_ATTEMPTS = 5


async def create_code(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    code_hash: str,
    expires_at: datetime,
    ip: str | None,
) -> PasswordResetCode:
    row = PasswordResetCode(user_id=user_id, code_hash=code_hash, expires_at=expires_at, ip=ip)
    session.add(row)
    await session.flush()
    return row


async def expire_open_codes(session: AsyncSession, user_id: uuid.UUID) -> int:
    """A new request supersedes any earlier code that is still live."""
    result = await session.execute(
        update(PasswordResetCode)
        .where(
            PasswordResetCode.user_id == user_id,
            PasswordResetCode.used_at.is_(None),
            PasswordResetCode.expires_at > func.now(),
        )
        .values(expires_at=func.now())
        .execution_options(synchronize_session=False)
    )
    assert isinstance(result, CursorResult)  # noqa: S101 — a bulk UPDATE always is
    return int(result.rowcount)


async def latest_open_code(session: AsyncSession, user_id: uuid.UUID) -> PasswordResetCode | None:
    """The newest live code (unused, unexpired, attempts left), for counting a wrong guess."""
    result = await session.scalars(
        select(PasswordResetCode)
        .where(
            PasswordResetCode.user_id == user_id,
            PasswordResetCode.used_at.is_(None),
            PasswordResetCode.expires_at > func.now(),
            PasswordResetCode.attempts < MAX_ATTEMPTS,
        )
        .order_by(PasswordResetCode.created_at.desc())
        .limit(1)
    )
    return result.first()


async def consume(
    session: AsyncSession, *, user_id: uuid.UUID, code_hash: str
) -> PasswordResetCode | None:
    """Mark the matching live code used and return it; None when no live code matches."""
    stmt = (
        update(PasswordResetCode)
        .where(
            PasswordResetCode.user_id == user_id,
            PasswordResetCode.code_hash == code_hash,
            PasswordResetCode.used_at.is_(None),
            PasswordResetCode.expires_at > func.now(),
            PasswordResetCode.attempts < MAX_ATTEMPTS,
        )
        .values(used_at=func.now())
        .returning(PasswordResetCode)
        .execution_options(synchronize_session=False)
    )
    return (await session.scalars(stmt)).one_or_none()


async def count_attempt(session: AsyncSession, code_id: uuid.UUID) -> None:
    await session.execute(
        update(PasswordResetCode)
        .where(PasswordResetCode.id == code_id)
        .values(attempts=PasswordResetCode.attempts + 1)
        .execution_options(synchronize_session=False)
    )
