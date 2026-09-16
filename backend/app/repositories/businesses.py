"""businesses — the tenant itself (docs/DATA_MAPPING.md §3.1).

The business row is the scope every other repository is parameterised by, so this
is the one place a lookup by bare id is legitimate. Callers must still hold a
verified membership for the business (see `app.api.deps`).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Business


async def get_business(session: AsyncSession, business_id: uuid.UUID) -> Business | None:
    return await session.get(Business, business_id)
