"""Business profile and settings (PRD FR-A3). OWNER-only; the router enforces the role."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import BusinessContext, ClientInfo
from app.core.errors import NotFoundError
from app.db.session import transaction
from app.models import Business
from app.repositories import businesses as business_repo
from app.schemas.business import BusinessUpdateRequest
from app.services import audit
from app.services.audit import AuditAction

ENTITY_TYPE = "business"


async def get_business(session: AsyncSession, ctx: BusinessContext) -> Business:
    business = await business_repo.get_business(session, ctx.business_id)
    if business is None:  # pragma: no cover — get_business_context just verified it
        raise NotFoundError("Business not found")
    return business


async def update_business(
    session: AsyncSession, ctx: BusinessContext, data: BusinessUpdateRequest, client: ClientInfo
) -> Business:
    """Apply the fields present in `data`; audit the ones that actually changed."""
    async with transaction(session):
        business = await business_repo.get_business_for_update(session, ctx.business_id)
        if business is None:  # pragma: no cover
            raise NotFoundError("Business not found")
        before: dict[str, object] = {}
        after: dict[str, object] = {}
        for field in sorted(data.model_fields_set, key=list(data.model_fields).index):
            value: object = getattr(data, field)
            if field == "settings" and data.settings is not None:
                # The whole validated object, defaults materialised, replaces the JSON.
                value = data.settings.model_dump()
            current = getattr(business, field)
            current_plain = current.value if hasattr(current, "value") else current
            new_plain = value.value if hasattr(value, "value") else value
            if current_plain == new_plain:
                continue
            before[field] = current_plain
            after[field] = new_plain
            setattr(business, field, value)
        if after:
            await session.flush()
            await audit.record(
                session,
                ctx,
                action=AuditAction.BUSINESS_UPDATE,
                entity_type=ENTITY_TYPE,
                entity_id=business.id,
                before=before,
                after=after,
                client=client,
            )
    return business
