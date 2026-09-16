"""Users and memberships (docs/DATA_MAPPING.md §3.2-§3.3).

`users` is the identity table and is not tenant-scoped; lookups by identifier are
therefore global by design. Memberships are always read for a specific
`(user_id, business_id)` pair or for one user, never listed across businesses.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BusinessMembership, User


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_phone(session: AsyncSession, phone: str) -> User | None:
    return (await session.scalars(select(User).where(User.phone == phone))).one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return (await session.scalars(select(User).where(User.email == email))).one_or_none()


async def get_membership(
    session: AsyncSession, *, user_id: uuid.UUID, business_id: uuid.UUID
) -> BusinessMembership | None:
    result = await session.scalars(
        select(BusinessMembership).where(
            BusinessMembership.user_id == user_id,
            BusinessMembership.business_id == business_id,
        )
    )
    return result.one_or_none()


async def list_memberships(session: AsyncSession, user_id: uuid.UUID) -> list[BusinessMembership]:
    """All memberships of one user, oldest first (deterministic for the MVP one-business case)."""
    result = await session.scalars(
        select(BusinessMembership)
        .where(BusinessMembership.user_id == user_id)
        .order_by(BusinessMembership.created_at, BusinessMembership.id)
    )
    return list(result)
