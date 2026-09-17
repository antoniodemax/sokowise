"""customers, credit_transactions (docs/DATA_MAPPING.md §3.8, §3.12).

`customers.balance` caches the ledger (positive = owes the business). Repayments are
ledger rows with their own payment method; they are never `payments` rows.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CHAR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import CreditEntryType, MoneyReceivedMethod, enum_check, enum_column


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("id", "business_id"),
        CheckConstraint(
            "credit_limit IS NULL OR credit_limit >= 0", name="credit_limit_non_negative"
        ),
        Index(
            "uq_customers_business_id_phone",
            "business_id",
            "phone",
            unique=True,
            postgresql_where=text("phone IS NOT NULL"),
        ),
        Index(None, "business_id", "name"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class CreditTransaction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "credit_transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_id", "business_id"], ["customers.id", "customers.business_id"]
        ),
        ForeignKeyConstraint(["sale_id", "business_id"], ["sales.id", "sales.business_id"]),
        ForeignKeyConstraint(
            ["payment_id", "business_id"], ["payments.id", "payments.business_id"]
        ),
        enum_check("entry_type", CreditEntryType, "entry_type"),
        CheckConstraint(
            "payment_method IS NULL OR payment_method IN ('CASH', 'MPESA')", name="payment_method"
        ),
        CheckConstraint(
            "entry_type <> 'ADJUSTMENT' OR reason IS NOT NULL", name="adjustment_has_reason"
        ),
        CheckConstraint(
            "entry_type <> 'REPAYMENT' OR payment_method IS NOT NULL",
            name="repayment_has_payment_method",
        ),
        Index(None, "business_id", "customer_id", "occurred_at"),
        # Period queries over the whole ledger (cash collected: REPAYMENTs in a period).
        Index(None, "business_id", "occurred_at"),
        Index(None, "sale_id"),
        Index(None, "payment_id"),
        Index(None, "created_by"),
        # Idempotent repayments/adjustments (same pattern as sales): a retry with the same
        # key and hash returns the original entry, a different hash is a 409. CHARGE and
        # REVERSAL rows come from sales and carry no key.
        Index(
            "uq_credit_transactions_business_id_idempotency_key",
            "business_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    entry_type: Mapped[CreditEntryType] = mapped_column(
        enum_column(CreditEntryType, 20), nullable=False
    )
    # Signed effect on balance: CHARGE +, REPAYMENT -, REVERSAL -, ADJUSTMENT ±.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    sale_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    # The CREDIT tender line that created a CHARGE.
    payment_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    payment_method: Mapped[MoneyReceivedMethod | None] = mapped_column(
        enum_column(MoneyReceivedMethod, 20)
    )
    reference: Mapped[str | None] = mapped_column(String(64))
    provider_transaction_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(String(255))
    idempotency_key: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    # SHA-256 of the canonical request payload; set together with idempotency_key.
    idempotency_hash: Mapped[str | None] = mapped_column(CHAR(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
