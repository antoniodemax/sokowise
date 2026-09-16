"""Business profile and settings (ROADMAP Phase 4; PRD FR-A3, §16).

Both routes are OWNER-only: the permission matrix gives STAFF neither view nor
edit of business settings. STAFF get the business basics from `GET /auth/me`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_info, require_owner
from app.core.context import BusinessContext, ClientInfo
from app.db.session import get_session
from app.models import Business
from app.schemas.business import BusinessDetail, BusinessSettings, BusinessUpdateRequest
from app.services import business as business_service

router = APIRouter(prefix="/business", tags=["business"])


def business_detail(business: Business) -> BusinessDetail:
    return BusinessDetail(
        id=business.id,
        name=business.name,
        business_type=business.business_type,
        phone=business.phone,
        address=business.address,
        currency=business.currency,
        timezone=business.timezone,
        settings=BusinessSettings.model_validate(business.settings),
        is_active=business.is_active,
        created_at=business.created_at,
    )


@router.get("", response_model=BusinessDetail)
async def get_business(
    ctx: Annotated[BusinessContext, Depends(require_owner)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BusinessDetail:
    return business_detail(await business_service.get_business(session, ctx))


@router.patch("", response_model=BusinessDetail)
async def update_business(
    payload: BusinessUpdateRequest,
    ctx: Annotated[BusinessContext, Depends(require_owner)],
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[ClientInfo, Depends(get_client_info)],
) -> BusinessDetail:
    return business_detail(await business_service.update_business(session, ctx, payload, client))
