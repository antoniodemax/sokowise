"""receipts, receipt_lines — supplier receipt intelligence (docs/DATA_MAPPING.md §3.17-§3.18).

A receipt is an *upload plus a proposal*: what the extraction layer read from the
image, what the backend matched it to, and what the owner finally confirmed. It
never moves stock by itself — confirmation goes through `services.inventory`, and
the resulting movements are linked from the lines for audit. The image lives in
the storage backend; only its key is stored here.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    ReceiptLineReview,
    ReceiptMatchStatus,
    ReceiptStatus,
    enum_check,
    enum_column,
)


class Receipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "receipts"
    __table_args__ = (
        UniqueConstraint("id", "business_id"),
        enum_check("status", ReceiptStatus, "status"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index(None, "business_id", "created_at"),
        Index(None, "business_id", "status"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[ReceiptStatus] = mapped_column(
        enum_column(ReceiptStatus, 20), nullable=False, default=ReceiptStatus.UPLOADED
    )
    # The upload: what was sent and where the bytes live (a storage key, never the bytes).
    original_filename: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(40), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # What the extraction layer read (all nullable: a receipt may show none of it).
    supplier_name: Mapped[str | None] = mapped_column(String(120))
    receipt_number: Mapped[str | None] = mapped_column(String(64))
    receipt_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    extracted_subtotal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    extracted_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    extraction_provider: Mapped[str | None] = mapped_column(String(40))
    extraction_model: Mapped[str | None] = mapped_column(String(60))
    extraction_error: Mapped[str | None] = mapped_column(String(255))
    # Backend validation notes for the reviewer, e.g. ["total_mismatch"]; never model prose.
    warnings: Mapped[list[str] | None] = mapped_column(JSONB)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )


class ReceiptLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "receipt_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["receipt_id", "business_id"], ["receipts.id", "receipts.business_id"]
        ),
        ForeignKeyConstraint(
            ["matched_product_id", "business_id"], ["products.id", "products.business_id"]
        ),
        enum_check("match_status", ReceiptMatchStatus, "match_status"),
        enum_check("review_status", ReceiptLineReview, "review_status"),
        CheckConstraint("extracted_quantity > 0", name="extracted_quantity_positive"),
        CheckConstraint("extracted_unit_cost >= 0", name="extracted_unit_cost_non_negative"),
        Index(None, "receipt_id", "position"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Extracted (untrusted until the owner confirms).
    extracted_name: Mapped[str] = mapped_column(String(160), nullable=False)
    extracted_sku: Mapped[str | None] = mapped_column(String(64))
    extracted_quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    extracted_unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    extracted_line_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    warnings: Mapped[list[str] | None] = mapped_column(JSONB)
    # Backend matching against the business's own catalogue.
    match_status: Mapped[ReceiptMatchStatus] = mapped_column(
        enum_column(ReceiptMatchStatus, 12), nullable=False, default=ReceiptMatchStatus.UNMATCHED
    )
    matched_product_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    candidate_product_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    # The owner's decision, filled at confirmation.
    review_status: Mapped[ReceiptLineReview] = mapped_column(
        enum_column(ReceiptLineReview, 10), nullable=False, default=ReceiptLineReview.PENDING
    )
    final_product_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    final_quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    final_unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # The movement created at confirmation (movements carry their own business_id).
    movement_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("inventory_movements.id")
    )
