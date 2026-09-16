"""inventory_movements — the append-only stock ledger (docs/DATA_MAPPING.md §3.7).

Only tracked products get movements. `quantity_after` is the running balance in
commit order (`created_at`); `occurred_at` is the business time used for reporting
and may be backdated. A void writes SALE_REVERSAL rows even for archived products.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from app.models.enums import MovementType, enum_check, enum_column


class InventoryMovement(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id", "business_id"], ["products.id", "products.business_id"]
        ),
        ForeignKeyConstraint(["sale_id", "business_id"], ["sales.id", "sales.business_id"]),
        enum_check("movement_type", MovementType, "movement_type"),
        CheckConstraint(
            "movement_type <> 'ADJUSTMENT' OR reason IS NOT NULL", name="adjustment_has_reason"
        ),
        CheckConstraint("quantity_after >= 0", name="quantity_after_non_negative"),
        Index(None, "business_id", "product_id", "occurred_at"),
        Index(None, "business_id", "product_id", "created_at"),
        Index(None, "sale_id"),
        Index(None, "created_by"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    movement_type: Mapped[MovementType] = mapped_column(
        enum_column(MovementType, 20), nullable=False
    )
    # Signed: SALE negative, RESTOCK positive, ADJUSTMENT either.
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    quantity_after: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    sale_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    supplier_name: Mapped[str | None] = mapped_column(String(120))
    reason: Mapped[str | None] = mapped_column(String(255))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
