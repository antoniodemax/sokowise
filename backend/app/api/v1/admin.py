"""Operator dashboard (docs/ARCHITECTURE.md §5.4).

Platform-wide, read-only figures for the people listed in `PLATFORM_ADMIN_PHONES`. Not a
tenant endpoint: there is no business context, and non-admins get a 404.
"""

import logging
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import platform
from app.api.deps import require_platform_admin
from app.db.session import get_session
from app.models import User
from app.schemas.admin import PlatformOverviewOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

AdminDep = Annotated[User, Depends(require_platform_admin)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/overview", response_model=PlatformOverviewOut)
async def overview(admin: AdminDep, session: SessionDep) -> PlatformOverviewOut:
    result = await platform.overview(session)
    logger.info("platform admin overview", extra={"user_id": str(admin.id)})
    return PlatformOverviewOut.model_validate(asdict(result))
