"""add mpesa messages

Pasted M-Pesa confirmation SMS, linked by transaction code to the payment or credit
repayment that records the money (docs/DATA_MAPPING.md §3.19). Plain FKs to payments and
credit_transactions; the tenant check is in the service. Partial unique index on
(business_id, code) makes a second paste of the same code a replay.

Revision ID: 6751abb9f456
Revises: 7f4db0684dfd
Create Date: 2026-09-18 05:40:15.377726
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6751abb9f456"
down_revision: str | Sequence[str] | None = "7f4db0684dfd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mpesa_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "UNPARSED",
                "UNMATCHED",
                "MATCHED",
                "IGNORED",
                name="mpesamessagestatus",
                native_enum=False,
                length=12,
            ),
            nullable=False,
        ),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("code", sa.String(length=10), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "POCHI",
                "TILL",
                "PAYBILL",
                "SEND_MONEY",
                "UNKNOWN",
                name="smskind",
                native_enum=False,
                length=12,
            ),
            nullable=True,
        ),
        sa.Column("sender_name", sa.String(length=120), nullable=True),
        sa.Column("sender_phone_masked", sa.String(length=20), nullable=True),
        sa.Column("sender_last3", sa.String(length=3), nullable=True),
        sa.Column("account_reference", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column("credit_transaction_id", sa.UUID(), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matched_by", sa.UUID(), nullable=True),
        sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ignored_by", sa.UUID(), nullable=True),
        sa.Column("ignore_reason", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'MATCHED' AND ((payment_id IS NULL) <> (credit_transaction_id IS NULL))) OR (status <> 'MATCHED' AND payment_id IS NULL AND credit_transaction_id IS NULL)",
            name=op.f("ck_mpesa_messages_matched_links_exactly_one"),
        ),
        sa.CheckConstraint(
            "(status <> 'UNPARSED' OR code IS NULL) AND (status IN ('UNPARSED', 'IGNORED') OR code IS NOT NULL)",
            name=op.f("ck_mpesa_messages_unparsed_has_no_code"),
        ),
        sa.CheckConstraint(
            "kind IN ('POCHI', 'TILL', 'PAYBILL', 'SEND_MONEY', 'UNKNOWN')",
            name=op.f("ck_mpesa_messages_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('UNPARSED', 'UNMATCHED', 'MATCHED', 'IGNORED')",
            name=op.f("ck_mpesa_messages_status"),
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount > 0", name=op.f("ck_mpesa_messages_amount_positive")
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_mpesa_messages_business_id_businesses"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_mpesa_messages_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["credit_transaction_id"],
            ["credit_transactions.id"],
            name=op.f("fk_mpesa_messages_credit_transaction_id_credit_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["ignored_by"], ["users.id"], name=op.f("fk_mpesa_messages_ignored_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["matched_by"], ["users.id"], name=op.f("fk_mpesa_messages_matched_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name=op.f("fk_mpesa_messages_payment_id_payments")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mpesa_messages")),
        sa.UniqueConstraint("id", "business_id", name=op.f("uq_mpesa_messages_id_business_id")),
    )
    op.create_index(
        op.f("ix_mpesa_messages_business_id_occurred_at"),
        "mpesa_messages",
        ["business_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mpesa_messages_business_id_status"),
        "mpesa_messages",
        ["business_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mpesa_messages_credit_transaction_id"),
        "mpesa_messages",
        ["credit_transaction_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_mpesa_messages_payment_id"), "mpesa_messages", ["payment_id"], unique=False
    )
    op.create_index(
        "uq_mpesa_messages_business_id_code",
        "mpesa_messages",
        ["business_id", "code"],
        unique=True,
        postgresql_where=sa.text("code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_mpesa_messages_business_id_code",
        table_name="mpesa_messages",
        postgresql_where=sa.text("code IS NOT NULL"),
    )
    op.drop_index(op.f("ix_mpesa_messages_payment_id"), table_name="mpesa_messages")
    op.drop_index(op.f("ix_mpesa_messages_credit_transaction_id"), table_name="mpesa_messages")
    op.drop_index(op.f("ix_mpesa_messages_business_id_status"), table_name="mpesa_messages")
    op.drop_index(op.f("ix_mpesa_messages_business_id_occurred_at"), table_name="mpesa_messages")
    op.drop_table("mpesa_messages")
