"""add idempotency to credit transactions

Repayments and adjustments (ROADMAP Phase 7) accept an Idempotency-Key so a
retried request cannot post a second ledger entry. Same pattern as
`sales.idempotency_key` / `idempotency_hash`; nullable because CHARGE and
REVERSAL rows are written by sales and carry no key of their own.

Revision ID: e73124c3e89a
Revises: b7a497cc6a27
Create Date: 2026-09-16 20:06:27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e73124c3e89a"
down_revision: str | Sequence[str] | None = "b7a497cc6a27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("credit_transactions", sa.Column("idempotency_key", sa.UUID(), nullable=True))
    op.add_column(
        "credit_transactions", sa.Column("idempotency_hash", sa.CHAR(length=64), nullable=True)
    )
    op.create_index(
        "uq_credit_transactions_business_id_idempotency_key",
        "credit_transactions",
        ["business_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_credit_transactions_business_id_idempotency_key",
        table_name="credit_transactions",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_column("credit_transactions", "idempotency_hash")
    op.drop_column("credit_transactions", "idempotency_key")
