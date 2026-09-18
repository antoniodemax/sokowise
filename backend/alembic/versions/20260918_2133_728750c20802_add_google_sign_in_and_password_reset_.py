"""add google sign-in and password reset codes

Revision ID: 728750c20802
Revises: 6161c7ab7a12
Create Date: 2026-09-18 21:33:41.388977
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "728750c20802"
down_revision: str | Sequence[str] | None = "6161c7ab7a12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_reset_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_password_reset_codes_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_codes")),
    )
    op.create_index(
        op.f("ix_password_reset_codes_user_id_created_at"),
        "password_reset_codes",
        ["user_id", "created_at"],
        unique=False,
    )
    op.add_column("users", sa.Column("google_sub", sa.String(length=255), nullable=True))
    op.alter_column("users", "password_hash", existing_type=sa.VARCHAR(length=255), nullable=True)
    op.create_unique_constraint(op.f("uq_users_google_sub"), "users", ["google_sub"])


def downgrade() -> None:
    # Fails while any Google-only account (password_hash NULL) exists; that is intended —
    # such rows cannot be represented by the previous schema.
    op.drop_constraint(op.f("uq_users_google_sub"), "users", type_="unique")
    op.alter_column("users", "password_hash", existing_type=sa.VARCHAR(length=255), nullable=False)
    op.drop_column("users", "google_sub")
    op.drop_index(
        op.f("ix_password_reset_codes_user_id_created_at"), table_name="password_reset_codes"
    )
    op.drop_table("password_reset_codes")
