"""Users and memberships (docs/DATA_MAPPING.md §3.2-§3.3).

`users` is the identity table and is not tenant-scoped; lookups by identifier are
therefore global by design. Memberships are always read for a specific
`(user_id, business_id)` pair or for one user, never listed across businesses.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import BusinessMembership, User
from app.models.enums import MembershipRole


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


# --- business-scoped (Phase 4) ---------------------------------------------------------
#
# Every function below takes `business_id` from a verified BusinessContext; there is no
# lookup of a membership by bare id.


async def list_members(session: AsyncSession, business_id: uuid.UUID) -> list[BusinessMembership]:
    """All memberships of one business with their users loaded, oldest first."""
    result = await session.scalars(
        select(BusinessMembership)
        .where(BusinessMembership.business_id == business_id)
        .options(selectinload(BusinessMembership.user))
        .order_by(BusinessMembership.created_at, BusinessMembership.id)
    )
    return list(result)


async def get_member(
    session: AsyncSession, *, business_id: uuid.UUID, user_id: uuid.UUID
) -> BusinessMembership | None:
    """One membership of the business, with its user; None if the user is not a member."""
    result = await session.scalars(
        select(BusinessMembership)
        .where(
            BusinessMembership.business_id == business_id,
            BusinessMembership.user_id == user_id,
        )
        .options(selectinload(BusinessMembership.user))
    )
    return result.one_or_none()


async def count_active_owners(session: AsyncSession, business_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(BusinessMembership)
        .where(
            BusinessMembership.business_id == business_id,
            BusinessMembership.role == MembershipRole.OWNER,
            BusinessMembership.is_active.is_(True),
        )
    )
    return int(count or 0)
