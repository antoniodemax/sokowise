"""expenses (docs/DATA_MAPPING.md §3.13). Restock spend is not an expense (PRD BR-6)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import MoneyReceivedMethod, enum_check, enum_column


class Expense(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        enum_check("payment_method", MoneyReceivedMethod, "payment_method"),
        Index(None, "business_id", "incurred_at"),
        Index(None, "created_by"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # Free text; the UI suggests RENT, TRANSPORT, UTILITIES, AIRTIME, SALARIES, LICENSES, OTHER.
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    payment_method: Mapped[MoneyReceivedMethod] = mapped_column(
        enum_column(MoneyReceivedMethod, 20), nullable=False
    )
    reference: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(255))
    incurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Soft delete; audited.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
