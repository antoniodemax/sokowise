"""add period indexes for movements and credit ledger

`inventory_movements (business_id, created_at, id)` serves the business-wide movements
listing (newest first, scanned backwards) and `credit_transactions (business_id, occurred_at)`
the per-period repayment sums in analytics; both were full ledger scans (Phase 15 review).

Revision ID: 7f4db0684dfd
Revises: ce922bf1c0c6
Create Date: 2026-09-17 19:07:00.732650
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7f4db0684dfd"
down_revision: str | Sequence[str] | None = "ce922bf1c0c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_credit_transactions_business_id_occurred_at"),
        "credit_transactions",
        ["business_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_movements_business_id_created_at_id"),
        "inventory_movements",
        ["business_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_inventory_movements_business_id_created_at_id"), table_name="inventory_movements"
    )
    op.drop_index(
        op.f("ix_credit_transactions_business_id_occurred_at"), table_name="credit_transactions"
    )
