"""refresh_tokens (docs/DATA_MAPPING.md §3.4).

Rows hold only the SHA-256 of the opaque token. `consume` is the single atomic
step of rotation: it revokes a live token and returns it in one UPDATE, so two
concurrent refreshes with the same token cannot both succeed (READ COMMITTED
re-evaluates the WHERE clause after the first writer commits).
"""

import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken


async def create_refresh_token(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    token_hash: str,
    expires_at: datetime,
    family_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> RefreshToken:
    """Insert a token. A new family starts when `family_id` is None (it equals the token's id)."""
    token_id = uuid.uuid4()
    row = RefreshToken(
        id=token_id,
        family_id=family_id or token_id,
        user_id=user_id,
        token_hash=token_hash,
        parent_id=parent_id,
        expires_at=expires_at,
        user_agent=user_agent,
        ip=ip,
    )
    session.add(row)
    await session.flush()
    return row


async def get_by_hash(session: AsyncSession, token_hash: str) -> RefreshToken | None:
    result = await session.scalars(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    return result.one_or_none()


async def consume(session: AsyncSession, token_hash: str) -> RefreshToken | None:
    """Revoke the live, unexpired token with this hash and return it; None if there is none."""
    stmt = (
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > func.now(),
        )
        .values(revoked_at=func.now())
        .returning(RefreshToken)
        .execution_options(synchronize_session=False)
    )
    return (await session.scalars(stmt)).one_or_none()


async def revoke_family(session: AsyncSession, family_id: uuid.UUID) -> int:
    """Revoke every live token in a family; returns how many were revoked."""
    return await _revoke_where(session, RefreshToken.family_id == family_id)


async def revoke_all_for_user(session: AsyncSession, user_id: uuid.UUID) -> int:
    return await _revoke_where(session, RefreshToken.user_id == user_id)


async def _revoke_where(session: AsyncSession, criterion: ColumnElement[bool]) -> int:
    result = await session.execute(
        update(RefreshToken)
        .where(criterion, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
        .execution_options(synchronize_session=False)
    )
    assert isinstance(result, CursorResult)  # noqa: S101 — a bulk UPDATE always is
    return int(result.rowcount)
