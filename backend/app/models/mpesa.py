"""mpesa_messages — pasted M-Pesa confirmation SMS (docs/DATA_MAPPING.md §3.19).

A message is a *record of money arriving on the shop's M-Pesa line*, not a money
movement. It never creates a sale, a payment or a ledger entry by itself: it is linked
to the payment or credit repayment that carries the same transaction code, either when
pasted (the code already exists) or when the sale/repayment is recorded later (the
reverse hook in `services.mpesa`). `raw_text`, sender name and phone are the shop's own
customer data: they stay in this table, are never logged, never exported and never
reach an AI tool.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import MpesaMessageStatus, SmsKind, enum_check, enum_column


class MpesaMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mpesa_messages"
    __table_args__ = (
        UniqueConstraint("id", "business_id"),
        enum_check("status", MpesaMessageStatus, "status"),
        enum_check("kind", SmsKind, "kind"),
        CheckConstraint("amount IS NULL OR amount > 0", name="amount_positive"),
        # Unparsed rows carry only the raw text; a row with a code is never UNPARSED.
        # (An ignored unparsed row keeps code NULL, so the rule is one-directional.)
        CheckConstraint(
            "(status <> 'UNPARSED' OR code IS NULL)"
            " AND (status IN ('UNPARSED', 'IGNORED') OR code IS NOT NULL)",
            name="unparsed_has_no_code",
        ),
        # MATCHED links exactly one of payment / repayment; other statuses link nothing.
        CheckConstraint(
            "(status = 'MATCHED' AND ((payment_id IS NULL) <> (credit_transaction_id IS NULL)))"
            " OR (status <> 'MATCHED' AND payment_id IS NULL AND credit_transaction_id IS NULL)",
            name="matched_links_exactly_one",
        ),
        # One row per transaction code per business; a second paste replays the first.
        Index(
            "uq_mpesa_messages_business_id_code",
            "business_id",
            "code",
            unique=True,
            postgresql_where=text("code IS NOT NULL"),
        ),
        Index(None, "business_id", "occurred_at"),
        Index(None, "business_id", "status"),
        Index(None, "payment_id"),
        Index(None, "credit_transaction_id"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[MpesaMessageStatus] = mapped_column(
        enum_column(MpesaMessageStatus, 12), nullable=False
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Parsed fields; all null for UNPARSED rows.
    code: Mapped[str | None] = mapped_column(String(10))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    kind: Mapped[SmsKind | None] = mapped_column(enum_column(SmsKind, 12))
    sender_name: Mapped[str | None] = mapped_column(String(120))
    sender_phone_masked: Mapped[str | None] = mapped_column(
        String(20)
    )  # as printed, e.g. 0712***456
    sender_last3: Mapped[str | None] = mapped_column(String(3))  # for customer-phone suggestions
    account_reference: Mapped[str | None] = mapped_column(String(64))  # Paybill account
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The link (plain FKs like receipt_lines.movement_id; tenant checked in the service).
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payments.id")
    )
    credit_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("credit_transactions.id")
    )
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    matched_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    ignored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ignored_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    ignore_reason: Mapped[str | None] = mapped_column(String(255))
