"""Operator dashboard (docs/ARCHITECTURE.md §5.4).

Platform-wide, read-only figures for the people listed in `PLATFORM_ADMIN_PHONES`. Not a
tenant endpoint: there is no business context, and non-admins get a 404.
"""

import logging
import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import platform
from app.api.deps import require_platform_admin, require_trusted_origin
from app.api.v1.receipts import get_storage
from app.db.session import get_session
from app.models import User
from app.schemas.admin import BusinessDeletedOut, PlatformOverviewOut
from app.services import platform_admin
from app.storage.base import BlobStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

AdminDep = Annotated[User, Depends(require_platform_admin)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
StorageDep = Annotated[BlobStorage, Depends(get_storage)]


@router.get("/overview", response_model=PlatformOverviewOut)
async def overview(admin: AdminDep, session: SessionDep) -> PlatformOverviewOut:
    result = await platform.overview(session)
    logger.info("platform admin overview", extra={"user_id": str(admin.id)})
    return PlatformOverviewOut.model_validate(asdict(result))


@router.delete(
    "/businesses/{business_id}",
    response_model=BusinessDeletedOut,
    dependencies=[Depends(require_trusted_origin)],
)
async def delete_business(
    business_id: uuid.UUID, admin: AdminDep, session: SessionDep, storage: StorageDep
) -> BusinessDeletedOut:
    """Remove a business account and everything it owns. Irreversible; see the service."""
    result = await platform_admin.delete_business(
        session, storage, admin=admin, business_id=business_id
    )
    return BusinessDeletedOut(
        business_id=result.business_id,
        name=result.name,
        users_deleted=result.users_deleted,
        receipt_images_deleted=result.receipt_images,
    )
