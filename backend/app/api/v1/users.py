"""Members of the caller's business (ROADMAP Phase 4; PRD FR-C1, FR-C2, FR-B6).

All routes are OWNER-only ("Manage users", PRD §16). `{user_id}` is resolved
through the membership for the caller's business, so a user of another business
is a 404 here.
"""

import uuid
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_info, require_owner
from app.core.context import BusinessContext, ClientInfo
from app.db.session import get_session
from app.models import BusinessMembership
from app.schemas.members import (
    MemberOut,
    MemberUpdateRequest,
    PasswordResetRequest,
    StaffCreateRequest,
)
from app.services import members as members_service

router = APIRouter(prefix="/users", tags=["users"])

OwnerCtx = Annotated[BusinessContext, Depends(require_owner)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClientDep = Annotated[ClientInfo, Depends(get_client_info)]


def member_out(member: BusinessMembership) -> MemberOut:
    user = member.user
    return MemberOut(
        user_id=user.id,
        full_name=user.full_name,
        phone=user.phone,
        email=user.email,
        role=member.role,
        is_active=member.is_active,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
        joined_at=member.created_at,
    )


@router.get("", response_model=list[MemberOut])
async def list_members(ctx: OwnerCtx, session: SessionDep) -> list[MemberOut]:
    return [member_out(m) for m in await members_service.list_members(session, ctx)]


@router.post("", status_code=HTTPStatus.CREATED, response_model=MemberOut)
async def create_staff(
    payload: StaffCreateRequest, ctx: OwnerCtx, session: SessionDep, client: ClientDep
) -> MemberOut:
    return member_out(await members_service.create_staff(session, ctx, payload, client))


@router.get("/{user_id}", response_model=MemberOut)
async def get_member(user_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> MemberOut:
    return member_out(await members_service.get_member(session, ctx, user_id))


@router.patch("/{user_id}", response_model=MemberOut)
async def update_member(
    user_id: uuid.UUID,
    payload: MemberUpdateRequest,
    ctx: OwnerCtx,
    session: SessionDep,
    client: ClientDep,
) -> MemberOut:
    return member_out(await members_service.update_member(session, ctx, user_id, payload, client))


@router.post("/{user_id}/reset-password", status_code=HTTPStatus.NO_CONTENT)
async def reset_password(
    user_id: uuid.UUID,
    payload: PasswordResetRequest,
    ctx: OwnerCtx,
    session: SessionDep,
    client: ClientDep,
) -> Response:
    await members_service.reset_password(session, ctx, user_id, payload, client)
    return Response(status_code=HTTPStatus.NO_CONTENT)
