"""Members of a business: STAFF creation, role changes, (de)activation, password reset
(PRD FR-C1, FR-C2; DATA_MAPPING §3.3).

Every function is scoped by `ctx.business_id`; a user who is not a member of that
business is simply "not found" (404), never "belongs to someone else".

Last-owner rule: a business always keeps at least one *active* OWNER. Any change
that would turn the last active owner into something else is refused with 409
`LAST_OWNER`. The business row is locked (`FOR UPDATE`) for the duration of a
membership change so two concurrent changes cannot both pass that check.
"""

import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import BusinessContext, ClientInfo
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.passwords import hash_password
from app.db.session import transaction
from app.models import BusinessMembership, User
from app.models.enums import MembershipRole
from app.repositories import businesses as business_repo
from app.repositories import refresh_tokens as token_repo
from app.repositories import users as user_repo
from app.schemas.members import MemberUpdateRequest, PasswordResetRequest, StaffCreateRequest
from app.services import audit
from app.services.audit import AuditAction

logger = logging.getLogger(__name__)

ENTITY_TYPE = "user"
_USER_UNIQUE_CONSTRAINTS = ("uq_users_phone", "uq_users_email")


def _not_found() -> NotFoundError:
    return NotFoundError("User not found")


async def list_members(session: AsyncSession, ctx: BusinessContext) -> list[BusinessMembership]:
    return await user_repo.list_members(session, ctx.business_id)


async def get_member(
    session: AsyncSession, ctx: BusinessContext, user_id: uuid.UUID
) -> BusinessMembership:
    member = await user_repo.get_member(session, business_id=ctx.business_id, user_id=user_id)
    if member is None:
        raise _not_found()
    return member


async def create_staff(
    session: AsyncSession, ctx: BusinessContext, data: StaffCreateRequest, client: ClientInfo
) -> BusinessMembership:
    """Create a user with `must_change_password=true` and a STAFF membership, atomically.

    One business per user in MVP (PRD FR-A4): an existing phone/email is a 409.
    """
    try:
        async with transaction(session):
            user = User(
                phone=data.phone,
                email=data.email,
                full_name=data.full_name,
                password_hash=hash_password(data.password),
                must_change_password=True,
            )
            session.add(user)
            await session.flush()
            member = BusinessMembership(
                business_id=ctx.business_id, user_id=user.id, role=MembershipRole.STAFF
            )
            session.add(member)
            await session.flush()
            await audit.record(
                session,
                ctx,
                action=AuditAction.USER_CREATE,
                entity_type=ENTITY_TYPE,
                entity_id=user.id,
                after={"role": MembershipRole.STAFF.value, "is_active": True},
                client=client,
            )
    except IntegrityError as exc:
        if any(name in str(exc.orig) for name in _USER_UNIQUE_CONSTRAINTS):
            raise ConflictError(
                "An account with this phone number or email already exists",
                code="ACCOUNT_EXISTS",
            ) from None
        raise
    logger.info(
        "staff user created", extra={"user_id": str(user.id), "business_id": str(ctx.business_id)}
    )
    return await get_member(session, ctx, user.id)


async def update_member(
    session: AsyncSession,
    ctx: BusinessContext,
    user_id: uuid.UUID,
    data: MemberUpdateRequest,
    client: ClientInfo,
) -> BusinessMembership:
    async with transaction(session):
        # Lock the business row first: membership changes for one business are serialised.
        business = await business_repo.get_business_for_update(session, ctx.business_id)
        if business is None:  # pragma: no cover — verified by get_business_context
            raise _not_found()
        member = await get_member(session, ctx, user_id)

        new_role = data.role if data.role is not None else member.role
        new_active = data.is_active if data.is_active is not None else member.is_active
        was_active_owner = member.role == MembershipRole.OWNER and member.is_active
        stays_active_owner = new_role == MembershipRole.OWNER and new_active
        if (
            was_active_owner
            and not stays_active_owner
            and await user_repo.count_active_owners(session, ctx.business_id) <= 1
        ):
            raise ConflictError("A business must keep at least one active owner", code="LAST_OWNER")

        if new_role != member.role:
            before_role, member.role = member.role, new_role
            await session.flush()
            await audit.record(
                session,
                ctx,
                action=AuditAction.USER_ROLE_CHANGE,
                entity_type=ENTITY_TYPE,
                entity_id=member.user_id,
                before={"role": before_role.value},
                after={"role": new_role.value},
                client=client,
            )
        if new_active != member.is_active:
            member.is_active = new_active
            await session.flush()
            if not new_active:
                # Deactivation ends the user's sessions immediately; the access token
                # dies at its next request via get_business_context anyway.
                await token_repo.revoke_all_for_user(session, member.user_id)
            await audit.record(
                session,
                ctx,
                action=AuditAction.USER_REACTIVATE if new_active else AuditAction.USER_DEACTIVATE,
                entity_type=ENTITY_TYPE,
                entity_id=member.user_id,
                before={"is_active": not new_active},
                after={"is_active": new_active},
                client=client,
            )
    return member


async def reset_password(
    session: AsyncSession,
    ctx: BusinessContext,
    user_id: uuid.UUID,
    data: PasswordResetRequest,
    client: ClientInfo,
) -> None:
    """Owner-initiated reset of a STAFF member's password (PRD FR-B6).

    Owners reset their own password through `POST /auth/change-password`, and owners are
    peers, so the target must be a STAFF member. The user must change the password at
    the next login and every existing session of theirs is revoked.
    """
    async with transaction(session):
        member = await get_member(session, ctx, user_id)
        if member.user_id == ctx.user_id:
            raise PermissionDeniedError("Use change-password for your own account")
        if member.role != MembershipRole.STAFF:
            raise PermissionDeniedError("Only staff passwords can be reset")
        member.user.password_hash = hash_password(data.password)
        member.user.must_change_password = True
        await session.flush()
        await token_repo.revoke_all_for_user(session, member.user_id)
        await audit.record(
            session,
            ctx,
            action=AuditAction.USER_PASSWORD_RESET,
            entity_type=ENTITY_TYPE,
            entity_id=member.user_id,
            client=client,
        )
    logger.info(
        "staff password reset",
        extra={"user_id": str(member.user_id), "business_id": str(ctx.business_id)},
    )
