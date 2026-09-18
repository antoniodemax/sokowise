"""add copilot proposals to ai messages

An assistant message may carry one proposed action (PRD FR-J7): data the model returned,
never executed by itself. Status tracks whether the owner confirmed it. The CHECKs are
hand-written: autogenerate does not emit them for existing tables.

Revision ID: 6161c7ab7a12
Revises: 6751abb9f456
Create Date: 2026-09-18 06:50:39.494128
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6161c7ab7a12"
down_revision: str | Sequence[str] | None = "6751abb9f456"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_messages", sa.Column("proposal", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "ai_messages",
        sa.Column(
            "proposal_status",
            sa.Enum(
                "PENDING",
                "APPLIED",
                "REJECTED",
                "EXPIRED",
                name="proposalstatus",
                native_enum=False,
                length=10,
            ),
            nullable=True,
        ),
    )
    op.add_column("ai_messages", sa.Column("proposal_entity_id", sa.UUID(), nullable=True))
    op.add_column(
        "ai_messages", sa.Column("proposal_applied_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "proposal_status",
        "ai_messages",
        "proposal_status IN ('PENDING', 'APPLIED', 'REJECTED', 'EXPIRED')",
    )
    op.create_check_constraint(
        "proposal_has_status",
        "ai_messages",
        "(proposal IS NULL) = (proposal_status IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("proposal_has_status", "ai_messages", type_="check")
    op.drop_constraint("proposal_status", "ai_messages", type_="check")
    op.drop_column("ai_messages", "proposal_applied_at")
    op.drop_column("ai_messages", "proposal_entity_id")
    op.drop_column("ai_messages", "proposal_status")
    op.drop_column("ai_messages", "proposal")
