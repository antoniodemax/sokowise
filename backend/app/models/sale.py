"""sales, sale_items, payments (docs/DATA_MAPPING.md §3.9-§3.11).

Sales are immutable once COMPLETED; corrections are voids. There is no cached cost
total on the sale: COGS is always computed from `sale_items` so lines with unknown
cost are counted rather than nulling out the sale (PRD BR-16).
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CHAR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
    SaleStatus,
    enum_check,
    enum_column,
)


class Sale(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sales"
    __table_args__ = (
        UniqueConstraint("id", "business_id"),
        # Idempotent creation (PRD FR-F6): same key + same hash → original sale,
        # same key + different hash → 409.
        UniqueConstraint("business_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["customer_id", "business_id"], ["customers.id", "customers.business_id"]
        ),
        enum_check("status", SaleStatus, "status"),
        CheckConstraint("subtotal >= 0", name="subtotal_non_negative"),
        CheckConstraint(
            "discount_amount >= 0 AND discount_amount <= subtotal", name="discount_within_subtotal"
        ),
        CheckConstraint("total_amount = subtotal - discount_amount", name="total_amount"),
        CheckConstraint(
            "status <> 'VOIDED' OR (voided_at IS NOT NULL AND void_reason IS NOT NULL)",
            name="voided_has_reason",
        ),
        Index("ix_sales_business_id_sold_at", "business_id", text("sold_at DESC")),
        Index(None, "business_id", "customer_id"),
        # STAFF see their own sales for today (PRD §16).
        Index(None, "business_id", "created_by", "sold_at"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    idempotency_key: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    # SHA-256 of the canonical request payload.
    idempotency_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    status: Mapped[SaleStatus] = mapped_column(enum_column(SaleStatus, 20), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    void_reason: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    items: Mapped[list["SaleItem"]] = relationship(back_populates="sale", lazy="raise")
    payments: Mapped[list["Payment"]] = relationship(back_populates="sale", lazy="raise")


class SaleItem(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "sale_items"
    __table_args__ = (
        ForeignKeyConstraint(["sale_id", "business_id"], ["sales.id", "sales.business_id"]),
        ForeignKeyConstraint(
            ["product_id", "business_id"], ["products.id", "products.business_id"]
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("unit_cost IS NULL OR unit_cost >= 0", name="unit_cost_non_negative"),
        CheckConstraint(
            "discount_allocated >= 0 AND discount_allocated <= line_total",
            name="discount_allocated_within_line",
        ),
        Index(None, "sale_id"),
        Index(None, "business_id", "product_id"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    sale_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    # Snapshots: later product edits never change history (PRD FR-F5).
    product_name: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    default_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # This line's share of sales.discount_amount, pro-rata by line_total with
    # largest-remainder rounding (PRD BR-14). Σ over the sale = discount_amount.
    discount_allocated: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )

    sale: Mapped[Sale] = relationship(
        back_populates="items", foreign_keys=[sale_id, business_id], lazy="raise"
    )


class Payment(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Tender lines of a sale. The M-Pesa extension seam: `status`/`provider` are always
    CONFIRMED/MANUAL in MVP. A CREDIT row is a receivable, not money received."""

    __tablename__ = "payments"
    __table_args__ = (
        # Lets credit_transactions.payment_id use a composite tenant FK.
        UniqueConstraint("id", "business_id"),
        ForeignKeyConstraint(["sale_id", "business_id"], ["sales.id", "sales.business_id"]),
        enum_check("method", PaymentMethod, "method"),
        enum_check("status", PaymentStatus, "status"),
        enum_check("provider", PaymentProvider, "provider"),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index(None, "business_id", "method", "created_at"),
        Index(None, "sale_id"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    sale_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(enum_column(PaymentMethod, 20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus, 20), nullable=False, server_default=PaymentStatus.CONFIRMED.value
    )
    # Manually typed M-Pesa code in MVP; format validated in Pydantic, not here.
    reference: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[PaymentProvider] = mapped_column(
        enum_column(PaymentProvider, 20),
        nullable=False,
        server_default=PaymentProvider.MANUAL.value,
    )
    # Future FK → mpesa_transactions.id (ARCHITECTURE §7).
    provider_transaction_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))

    sale: Mapped[Sale] = relationship(
        back_populates="payments", foreign_keys=[sale_id, business_id], lazy="raise"
    )
