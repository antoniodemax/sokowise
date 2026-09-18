"""Operator actions on whole businesses (docs/ARCHITECTURE.md §5.4).

`delete_business` removes a business account and everything it owns: every tenant row,
its memberships, the receipt images in storage, and any user whose only membership was
this business (a person who also belongs to another business keeps their login). It is
the one write path that reaches across tenants, so it is reachable only through
`require_platform_admin`, refuses to delete a business the admin belongs to (use another
admin account), and is irreversible. There is nowhere to audit it after the fact — the
business's audit rows go with it — so it is logged at INFO with the admin's user id.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.db.session import transaction
from app.models import (
    AIConversation,
    AIMessage,
    AuditLog,
    Business,
    BusinessMembership,
    Category,
    CreditTransaction,
    Customer,
    Expense,
    InventoryMovement,
    MpesaMessage,
    PasswordResetCode,
    Payment,
    Product,
    Receipt,
    ReceiptLine,
    RefreshToken,
    Sale,
    SaleItem,
    User,
)
from app.storage.base import BlobStorage

logger = logging.getLogger(__name__)

# Children before parents: each table is emptied before any table it points at.
_TENANT_TABLES_IN_DELETE_ORDER = (
    MpesaMessage,
    ReceiptLine,
    Receipt,
    AIMessage,
    AIConversation,
    CreditTransaction,
    Payment,
    SaleItem,
    InventoryMovement,
    Sale,
    Expense,
    Customer,
    Product,
    Category,
    AuditLog,
    BusinessMembership,
)


class OwnBusinessError(ConflictError):
    code = "OWN_BUSINESS"


@dataclass(frozen=True, slots=True)
class Deleted:
    business_id: uuid.UUID
    name: str
    users_deleted: int
    receipt_images: int


async def delete_business(
    session: AsyncSession, storage: BlobStorage, *, admin: User, business_id: uuid.UUID
) -> Deleted:
    async with transaction(session):
        business = await session.get(Business, business_id)
        if business is None:
            raise NotFoundError("Business not found")
        member_ids = list(
            await session.scalars(
                select(BusinessMembership.user_id).where(
                    BusinessMembership.business_id == business_id
                )
            )
        )
        if admin.id in member_ids:
            raise OwnBusinessError(
                "You belong to this business. Delete it from another admin account."
            )
        # Users who belong to nothing else once this business is gone.
        others = set(
            await session.scalars(
                select(BusinessMembership.user_id).where(
                    BusinessMembership.user_id.in_(member_ids),
                    BusinessMembership.business_id != business_id,
                )
            )
        )
        orphan_ids = [user_id for user_id in member_ids if user_id not in others]
        image_keys = list(
            await session.scalars(
                select(Receipt.storage_key).where(Receipt.business_id == business_id)
            )
        )
        name = business.name

        for table in _TENANT_TABLES_IN_DELETE_ORDER:
            await session.execute(
                delete(table)
                .where(table.__table__.c.business_id == business_id)
                .execution_options(synchronize_session=False)
            )
        await session.execute(
            delete(Business)
            .where(Business.id == business_id)
            .execution_options(synchronize_session=False)
        )
        if orphan_ids:
            await session.execute(
                delete(RefreshToken)
                .where(RefreshToken.user_id.in_(orphan_ids))
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                delete(PasswordResetCode)
                .where(PasswordResetCode.user_id.in_(orphan_ids))
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                delete(User)
                .where(User.id.in_(orphan_ids))
                .execution_options(synchronize_session=False)
            )

    # Files last: the rows are gone, so a failed unlink leaves nothing dangling in the app.
    for key in image_keys:
        try:
            await storage.delete(key)
        except OSError:  # pragma: no cover — best effort; the image is unreachable anyway
            logger.warning("receipt image not removed", extra={"key_prefix": key[:16]})

    logger.info(
        "business deleted by platform admin",
        extra={
            "business_id": str(business_id),
            "admin_user_id": str(admin.id),
            "users_deleted": len(orphan_ids),
            "receipt_images": len(image_keys),
        },
    )
    return Deleted(
        business_id=business_id,
        name=name,
        users_deleted=len(orphan_ids),
        receipt_images=len(image_keys),
    )


__all__ = ["Deleted", "OwnBusinessError", "delete_business"]
