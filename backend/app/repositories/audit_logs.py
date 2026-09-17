"""audit_logs — append-only (docs/DATA_MAPPING.md §3.16).

Rows are added inside the caller's transaction and never updated or deleted.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def add(session: AsyncSession, entry: AuditLog) -> AuditLog:
    session.add(entry)
    await session.flush()
    return entry


MAX_LIST_LIMIT = 500


async def list_for_business(
    session: AsyncSession, business_id: uuid.UUID, *, limit: int = 100
) -> list[AuditLog]:
    result = await session.scalars(
        select(AuditLog)
        .where(AuditLog.business_id == business_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
        .limit(min(limit, MAX_LIST_LIMIT))
    )
    return list(result)
