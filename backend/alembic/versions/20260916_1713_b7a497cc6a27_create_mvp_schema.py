"""create mvp schema

Revision ID: b7a497cc6a27
Revises:
Create Date: 2026-09-16 17:13:53.090255
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7a497cc6a27"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "businesses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "business_type",
            sa.Enum(
                "GENERAL_SHOP",
                "BOUTIQUE",
                "SALON",
                "RESTAURANT",
                "ELECTRONICS",
                "OTHER",
                name="businesstype",
                native_enum=False,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.CHAR(length=3), server_default="KES", nullable=False),
        sa.Column(
            "timezone", sa.String(length=64), server_default="Africa/Nairobi", nullable=False
        ),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
            "business_type IN ('GENERAL_SHOP', 'BOUTIQUE', 'SALON', 'RESTAURANT', 'ELECTRONICS', 'OTHER')",
            name=op.f("ck_businesses_business_type"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_businesses")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("phone", name=op.f("uq_users_phone")),
    )
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_ai_conversations_business_id_businesses"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_ai_conversations_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_conversations")),
        sa.UniqueConstraint("id", "business_id", name=op.f("uq_ai_conversations_id_business_id")),
    )
    op.create_index(
        op.f("ix_ai_conversations_business_id_user_id"),
        "ai_conversations",
        ["business_id", "user_id"],
        unique=False,
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_audit_logs_actor_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["business_id"], ["businesses.id"], name=op.f("fk_audit_logs_business_id_businesses")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(
        op.f("ix_audit_logs_actor_user_id"), "audit_logs", ["actor_user_id"], unique=False
    )
    op.create_index(
        op.f("ix_audit_logs_business_id_created_at"),
        "audit_logs",
        ["business_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_logs_business_id_entity_type_entity_id"),
        "audit_logs",
        ["business_id", "entity_type", "entity_id"],
        unique=False,
    )
    op.create_table(
        "business_memberships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("OWNER", "STAFF", name="membershiprole", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.CheckConstraint("role IN ('OWNER', 'STAFF')", name=op.f("ck_business_memberships_role")),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_business_memberships_business_id_businesses"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_business_memberships_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_business_memberships")),
        sa.UniqueConstraint(
            "business_id", "user_id", name=op.f("uq_business_memberships_business_id_user_id")
        ),
    )
    op.create_index(
        op.f("ix_business_memberships_user_id"), "business_memberships", ["user_id"], unique=False
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["business_id"], ["businesses.id"], name=op.f("fk_categories_business_id_businesses")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("id", "business_id", name=op.f("uq_categories_id_business_id")),
    )
    op.create_index(
        "uq_categories_business_id_lower_name",
        "categories",
        ["business_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_table(
        "customers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("credit_limit", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column(
            "balance",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
            "credit_limit IS NULL OR credit_limit >= 0",
            name=op.f("ck_customers_credit_limit_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id"], ["businesses.id"], name=op.f("fk_customers_business_id_businesses")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("id", "business_id", name=op.f("uq_customers_id_business_id")),
    )
    op.create_index(
        op.f("ix_customers_business_id_name"), "customers", ["business_id", "name"], unique=False
    )
    op.create_index(
        "uq_customers_business_id_phone",
        "customers",
        ["business_id", "phone"],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )
    op.create_table(
        "expenses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column(
            "payment_method",
            sa.Enum("CASH", "MPESA", name="moneyreceivedmethod", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("reference", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("incurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
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
            "payment_method IN ('CASH', 'MPESA')", name=op.f("ck_expenses_payment_method")
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_expenses_amount_positive")),
        sa.ForeignKeyConstraint(
            ["business_id"], ["businesses.id"], name=op.f("fk_expenses_business_id_businesses")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_expenses_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expenses")),
    )
    op.create_index(
        op.f("ix_expenses_business_id_incurred_at"),
        "expenses",
        ["business_id", "incurred_at"],
        unique=False,
    )
    op.create_index(op.f("ix_expenses_created_by"), "expenses", ["created_by"], unique=False)
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_parent_id_refresh_tokens"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_refresh_tokens_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "ai_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", name="aimessagerole", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model", sa.String(length=60), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
        sa.Column("stop_reason", sa.String(length=30), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_ai_messages_role")),
        sa.ForeignKeyConstraint(
            ["business_id"], ["businesses.id"], name=op.f("fk_ai_messages_business_id_businesses")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "business_id"],
            ["ai_conversations.id", "ai_conversations.business_id"],
            name=op.f("fk_ai_messages_conversation_id_business_id_ai_conversations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_messages")),
    )
    op.create_index(
        op.f("ix_ai_messages_business_id_role_created_at"),
        "ai_messages",
        ["business_id", "role", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_messages_conversation_id_created_at"),
        "ai_messages",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "products",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("sku", sa.String(length=60), nullable=True),
        sa.Column("barcode", sa.String(length=64), nullable=True),
        sa.Column(
            "unit",
            sa.Enum(
                "piece",
                "kg",
                "g",
                "litre",
                "ml",
                "metre",
                "pack",
                "service",
                "other",
                name="productunit",
                native_enum=False,
                length=20,
            ),
            server_default="piece",
            nullable=False,
        ),
        sa.Column("selling_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("cost_price", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("track_inventory", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "stock_quantity",
            sa.Numeric(precision=12, scale=3),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("low_stock_threshold", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
            "unit IN ('piece', 'kg', 'g', 'litre', 'ml', 'metre', 'pack', 'service', 'other')",
            name=op.f("ck_products_unit"),
        ),
        sa.CheckConstraint(
            "cost_price IS NULL OR cost_price >= 0",
            name=op.f("ck_products_cost_price_non_negative"),
        ),
        sa.CheckConstraint(
            "selling_price >= 0", name=op.f("ck_products_selling_price_non_negative")
        ),
        sa.CheckConstraint(
            "stock_quantity >= 0", name=op.f("ck_products_stock_quantity_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["business_id"], ["businesses.id"], name=op.f("fk_products_business_id_businesses")
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "business_id"],
            ["categories.id", "categories.business_id"],
            name=op.f("fk_products_category_id_business_id_categories"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("id", "business_id", name=op.f("uq_products_id_business_id")),
    )
    op.create_index(
        op.f("ix_products_business_id_name"), "products", ["business_id", "name"], unique=False
    )
    op.create_index(op.f("ix_products_category_id"), "products", ["category_id"], unique=False)
    op.create_index(
        "uq_products_business_id_barcode",
        "products",
        ["business_id", "barcode"],
        unique=True,
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )
    op.create_index(
        "uq_products_business_id_lower_name_active",
        "products",
        ["business_id", sa.literal_column("lower(name)")],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "uq_products_business_id_sku",
        "products",
        ["business_id", "sku"],
        unique=True,
        postgresql_where=sa.text("sku IS NOT NULL"),
    )
    op.create_table(
        "sales",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.UUID(), nullable=False),
        sa.Column("idempotency_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum("COMPLETED", "VOIDED", name="salestatus", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "discount_amount",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by", sa.UUID(), nullable=True),
        sa.Column("void_reason", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
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
            "status <> 'VOIDED' OR (voided_at IS NOT NULL AND void_reason IS NOT NULL)",
            name=op.f("ck_sales_voided_has_reason"),
        ),
        sa.CheckConstraint("status IN ('COMPLETED', 'VOIDED')", name=op.f("ck_sales_status")),
        sa.CheckConstraint(
            "discount_amount >= 0 AND discount_amount <= subtotal",
            name=op.f("ck_sales_discount_within_subtotal"),
        ),
        sa.CheckConstraint("subtotal >= 0", name=op.f("ck_sales_subtotal_non_negative")),
        sa.CheckConstraint(
            "total_amount = subtotal - discount_amount", name=op.f("ck_sales_total_amount")
        ),
        sa.ForeignKeyConstraint(
            ["business_id"], ["businesses.id"], name=op.f("fk_sales_business_id_businesses")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_sales_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["customer_id", "business_id"],
            ["customers.id", "customers.business_id"],
            name=op.f("fk_sales_customer_id_business_id_customers"),
        ),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], name=op.f("fk_sales_voided_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales")),
        sa.UniqueConstraint(
            "business_id", "idempotency_key", name=op.f("uq_sales_business_id_idempotency_key")
        ),
        sa.UniqueConstraint("id", "business_id", name=op.f("uq_sales_id_business_id")),
    )
    op.create_index(
        op.f("ix_sales_business_id_created_by_sold_at"),
        "sales",
        ["business_id", "created_by", "sold_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sales_business_id_customer_id"),
        "sales",
        ["business_id", "customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_sales_business_id_sold_at",
        "sales",
        ["business_id", sa.literal_column("sold_at DESC")],
        unique=False,
    )
    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column(
            "movement_type",
            sa.Enum(
                "INITIAL",
                "RESTOCK",
                "SALE",
                "SALE_REVERSAL",
                "ADJUSTMENT",
                name="movementtype",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("quantity_delta", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("quantity_after", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("total_cost", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("sale_id", sa.UUID(), nullable=True),
        sa.Column("supplier_name", sa.String(length=120), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "movement_type <> 'ADJUSTMENT' OR reason IS NOT NULL",
            name=op.f("ck_inventory_movements_adjustment_has_reason"),
        ),
        sa.CheckConstraint(
            "movement_type IN ('INITIAL', 'RESTOCK', 'SALE', 'SALE_REVERSAL', 'ADJUSTMENT')",
            name=op.f("ck_inventory_movements_movement_type"),
        ),
        sa.CheckConstraint(
            "quantity_after >= 0", name=op.f("ck_inventory_movements_quantity_after_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_inventory_movements_business_id_businesses"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_inventory_movements_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["product_id", "business_id"],
            ["products.id", "products.business_id"],
            name=op.f("fk_inventory_movements_product_id_business_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["sale_id", "business_id"],
            ["sales.id", "sales.business_id"],
            name=op.f("fk_inventory_movements_sale_id_business_id_sales"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_movements")),
    )
    op.create_index(
        op.f("ix_inventory_movements_business_id_product_id_created_at"),
        "inventory_movements",
        ["business_id", "product_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_movements_business_id_product_id_occurred_at"),
        "inventory_movements",
        ["business_id", "product_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_movements_created_by"),
        "inventory_movements",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_movements_sale_id"), "inventory_movements", ["sale_id"], unique=False
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("sale_id", sa.UUID(), nullable=False),
        sa.Column(
            "method",
            sa.Enum("CASH", "MPESA", "CREDIT", name="paymentmethod", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "CONFIRMED", "PENDING", "FAILED", name="paymentstatus", native_enum=False, length=20
            ),
            server_default="CONFIRMED",
            nullable=False,
        ),
        sa.Column("reference", sa.String(length=64), nullable=True),
        sa.Column(
            "provider",
            sa.Enum("MANUAL", name="paymentprovider", native_enum=False, length=20),
            server_default="MANUAL",
            nullable=False,
        ),
        sa.Column("provider_transaction_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "method IN ('CASH', 'MPESA', 'CREDIT')", name=op.f("ck_payments_method")
        ),
        sa.CheckConstraint("provider IN ('MANUAL')", name=op.f("ck_payments_provider")),
        sa.CheckConstraint(
            "status IN ('CONFIRMED', 'PENDING', 'FAILED')", name=op.f("ck_payments_status")
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payments_amount_positive")),
        sa.ForeignKeyConstraint(
            ["business_id"], ["businesses.id"], name=op.f("fk_payments_business_id_businesses")
        ),
        sa.ForeignKeyConstraint(
            ["sale_id", "business_id"],
            ["sales.id", "sales.business_id"],
            name=op.f("fk_payments_sale_id_business_id_sales"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("id", "business_id", name=op.f("uq_payments_id_business_id")),
    )
    op.create_index(
        op.f("ix_payments_business_id_method_created_at"),
        "payments",
        ["business_id", "method", "created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_payments_sale_id"), "payments", ["sale_id"], unique=False)
    op.create_table(
        "sale_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("sale_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("product_name", sa.String(length=120), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("default_unit_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("line_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "discount_allocated",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "discount_allocated >= 0 AND discount_allocated <= line_total",
            name=op.f("ck_sale_items_discount_allocated_within_line"),
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_sale_items_quantity_positive")),
        sa.CheckConstraint(
            "unit_cost IS NULL OR unit_cost >= 0", name=op.f("ck_sale_items_unit_cost_non_negative")
        ),
        sa.CheckConstraint("unit_price >= 0", name=op.f("ck_sale_items_unit_price_non_negative")),
        sa.ForeignKeyConstraint(
            ["business_id"], ["businesses.id"], name=op.f("fk_sale_items_business_id_businesses")
        ),
        sa.ForeignKeyConstraint(
            ["product_id", "business_id"],
            ["products.id", "products.business_id"],
            name=op.f("fk_sale_items_product_id_business_id_products"),
        ),
        sa.ForeignKeyConstraint(
            ["sale_id", "business_id"],
            ["sales.id", "sales.business_id"],
            name=op.f("fk_sale_items_sale_id_business_id_sales"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_items")),
    )
    op.create_index(
        op.f("ix_sale_items_business_id_product_id"),
        "sale_items",
        ["business_id", "product_id"],
        unique=False,
    )
    op.create_index(op.f("ix_sale_items_sale_id"), "sale_items", ["sale_id"], unique=False)
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("business_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column(
            "entry_type",
            sa.Enum(
                "CHARGE",
                "REPAYMENT",
                "REVERSAL",
                "ADJUSTMENT",
                name="creditentrytype",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("sale_id", sa.UUID(), nullable=True),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column(
            "payment_method",
            sa.Enum("CASH", "MPESA", name="moneyreceivedmethod", native_enum=False, length=20),
            nullable=True,
        ),
        sa.Column("reference", sa.String(length=64), nullable=True),
        sa.Column("provider_transaction_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entry_type <> 'ADJUSTMENT' OR reason IS NOT NULL",
            name=op.f("ck_credit_transactions_adjustment_has_reason"),
        ),
        sa.CheckConstraint(
            "entry_type <> 'REPAYMENT' OR payment_method IS NOT NULL",
            name=op.f("ck_credit_transactions_repayment_has_payment_method"),
        ),
        sa.CheckConstraint(
            "entry_type IN ('CHARGE', 'REPAYMENT', 'REVERSAL', 'ADJUSTMENT')",
            name=op.f("ck_credit_transactions_entry_type"),
        ),
        sa.CheckConstraint(
            "payment_method IS NULL OR payment_method IN ('CASH', 'MPESA')",
            name=op.f("ck_credit_transactions_payment_method"),
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_credit_transactions_business_id_businesses"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_credit_transactions_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["customer_id", "business_id"],
            ["customers.id", "customers.business_id"],
            name=op.f("fk_credit_transactions_customer_id_business_id_customers"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_id", "business_id"],
            ["payments.id", "payments.business_id"],
            name=op.f("fk_credit_transactions_payment_id_business_id_payments"),
        ),
        sa.ForeignKeyConstraint(
            ["sale_id", "business_id"],
            ["sales.id", "sales.business_id"],
            name=op.f("fk_credit_transactions_sale_id_business_id_sales"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_transactions")),
    )
    op.create_index(
        op.f("ix_credit_transactions_business_id_customer_id_occurred_at"),
        "credit_transactions",
        ["business_id", "customer_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_credit_transactions_created_by"),
        "credit_transactions",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_credit_transactions_payment_id"),
        "credit_transactions",
        ["payment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_credit_transactions_sale_id"), "credit_transactions", ["sale_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_credit_transactions_sale_id"), table_name="credit_transactions")
    op.drop_index(op.f("ix_credit_transactions_payment_id"), table_name="credit_transactions")
    op.drop_index(op.f("ix_credit_transactions_created_by"), table_name="credit_transactions")
    op.drop_index(
        op.f("ix_credit_transactions_business_id_customer_id_occurred_at"),
        table_name="credit_transactions",
    )
    op.drop_table("credit_transactions")
    op.drop_index(op.f("ix_sale_items_sale_id"), table_name="sale_items")
    op.drop_index(op.f("ix_sale_items_business_id_product_id"), table_name="sale_items")
    op.drop_table("sale_items")
    op.drop_index(op.f("ix_payments_sale_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_business_id_method_created_at"), table_name="payments")
    op.drop_table("payments")
    op.drop_index(op.f("ix_inventory_movements_sale_id"), table_name="inventory_movements")
    op.drop_index(op.f("ix_inventory_movements_created_by"), table_name="inventory_movements")
    op.drop_index(
        op.f("ix_inventory_movements_business_id_product_id_occurred_at"),
        table_name="inventory_movements",
    )
    op.drop_index(
        op.f("ix_inventory_movements_business_id_product_id_created_at"),
        table_name="inventory_movements",
    )
    op.drop_table("inventory_movements")
    op.drop_index("ix_sales_business_id_sold_at", table_name="sales")
    op.drop_index(op.f("ix_sales_business_id_customer_id"), table_name="sales")
    op.drop_index(op.f("ix_sales_business_id_created_by_sold_at"), table_name="sales")
    op.drop_table("sales")
    op.drop_index(
        "uq_products_business_id_sku",
        table_name="products",
        postgresql_where=sa.text("sku IS NOT NULL"),
    )
    op.drop_index(
        "uq_products_business_id_lower_name_active",
        table_name="products",
        postgresql_where=sa.text("is_active"),
    )
    op.drop_index(
        "uq_products_business_id_barcode",
        table_name="products",
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )
    op.drop_index(op.f("ix_products_category_id"), table_name="products")
    op.drop_index(op.f("ix_products_business_id_name"), table_name="products")
    op.drop_table("products")
    op.drop_index(op.f("ix_ai_messages_conversation_id_created_at"), table_name="ai_messages")
    op.drop_index(op.f("ix_ai_messages_business_id_role_created_at"), table_name="ai_messages")
    op.drop_table("ai_messages")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_expenses_created_by"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_business_id_incurred_at"), table_name="expenses")
    op.drop_table("expenses")
    op.drop_index(
        "uq_customers_business_id_phone",
        table_name="customers",
        postgresql_where=sa.text("phone IS NOT NULL"),
    )
    op.drop_index(op.f("ix_customers_business_id_name"), table_name="customers")
    op.drop_table("customers")
    op.drop_index("uq_categories_business_id_lower_name", table_name="categories")
    op.drop_table("categories")
    op.drop_index(op.f("ix_business_memberships_user_id"), table_name="business_memberships")
    op.drop_table("business_memberships")
    op.drop_index(op.f("ix_audit_logs_business_id_entity_type_entity_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_business_id_created_at"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_user_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(op.f("ix_ai_conversations_business_id_user_id"), table_name="ai_conversations")
    op.drop_table("ai_conversations")
    op.drop_table("users")
    op.drop_table("businesses")
