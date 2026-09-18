"""Structural checks on the migrated schema: tenant columns, composite FKs,
uniqueness, indexes and enum CHECKs (docs/DATA_MAPPING.md §2, §7)."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.db

TENANT_TABLES = {
    "business_memberships",
    "categories",
    "products",
    "inventory_movements",
    "customers",
    "sales",
    "sale_items",
    "payments",
    "credit_transactions",
    "expenses",
    "ai_conversations",
    "ai_messages",
    "receipts",
    "receipt_lines",
    "mpesa_messages",
    "audit_logs",
}


def _schema(connection: Connection) -> dict[str, dict[str, Any]]:
    inspector = inspect(connection)
    return {
        table: {
            "columns": {column["name"]: column for column in inspector.get_columns(table)},
            "uniques": [
                tuple(uc["column_names"]) for uc in inspector.get_unique_constraints(table)
            ],
            "fks": inspector.get_foreign_keys(table),
            "checks": {ck["name"]: ck["sqltext"] for ck in inspector.get_check_constraints(table)},
            "indexes": inspector.get_indexes(table),
        }
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }


async def _load_schema(url: str) -> dict[str, dict[str, Any]]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_schema)
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def schema(migrated_database: str) -> dict[str, dict[str, Any]]:
    """One reflection of the migrated schema shared by every check in this module."""
    return asyncio.run(_load_schema(migrated_database))


def _fk(schema: dict[str, Any], table: str, columns: list[str]) -> dict[str, Any]:
    for fk in schema[table]["fks"]:
        if fk["constrained_columns"] == columns:
            return dict(fk)
    raise AssertionError(f"{table} has no FK on {columns}")


def _index(schema: dict[str, Any], table: str, name: str) -> dict[str, Any]:
    for index in schema[table]["indexes"]:
        if index["name"] == name:
            return dict(index)
    raise AssertionError(f"{table} has no index {name}")


def test_every_tenant_owned_table_has_non_nullable_business_id(schema: dict[str, Any]) -> None:
    for table in TENANT_TABLES:
        column = schema[table]["columns"]["business_id"]
        assert column["nullable"] is False, table
        assert _fk(schema, table, ["business_id"])["referred_table"] == "businesses", table


@pytest.mark.parametrize(
    ("table", "columns", "parent"),
    [
        ("products", ["category_id", "business_id"], "categories"),
        ("inventory_movements", ["product_id", "business_id"], "products"),
        ("inventory_movements", ["sale_id", "business_id"], "sales"),
        ("sales", ["customer_id", "business_id"], "customers"),
        ("sale_items", ["sale_id", "business_id"], "sales"),
        ("sale_items", ["product_id", "business_id"], "products"),
        ("payments", ["sale_id", "business_id"], "sales"),
        ("credit_transactions", ["customer_id", "business_id"], "customers"),
        ("credit_transactions", ["sale_id", "business_id"], "sales"),
        ("credit_transactions", ["payment_id", "business_id"], "payments"),
        ("ai_messages", ["conversation_id", "business_id"], "ai_conversations"),
    ],
)
def test_composite_tenant_foreign_keys(
    schema: dict[str, Any], table: str, columns: list[str], parent: str
) -> None:
    fk = _fk(schema, table, columns)
    assert fk["referred_table"] == parent
    assert fk["referred_columns"] == ["id", "business_id"]


@pytest.mark.parametrize(
    "table", ["categories", "products", "customers", "sales", "payments", "ai_conversations"]
)
def test_parents_of_composite_fks_have_id_business_id_unique(
    schema: dict[str, Any], table: str
) -> None:
    assert ("id", "business_id") in schema[table]["uniques"]


def test_authentication_columns(schema: dict[str, Any]) -> None:
    users = schema["users"]["columns"]
    assert users["must_change_password"]["nullable"] is False
    # NULL for Google-only accounts (DATA_MAPPING §3.2); password login refuses those.
    assert users["password_hash"]["nullable"] is True
    assert users["google_sub"]["nullable"] is True
    assert ("google_sub",) in schema["users"]["uniques"] or _index(
        schema, "users", "uq_users_google_sub"
    )
    assert ("phone",) in schema["users"]["uniques"] or _index(schema, "users", "uq_users_phone")
    tokens = schema["refresh_tokens"]["columns"]
    assert tokens["family_id"]["nullable"] is False
    assert "parent_id" in tokens
    assert "revoked_at" in tokens
    assert ("business_id", "user_id") in schema["business_memberships"]["uniques"]


def test_sale_columns_from_the_phase_0_review(schema: dict[str, Any]) -> None:
    assert schema["sales"]["columns"]["idempotency_hash"]["nullable"] is False
    assert ("business_id", "idempotency_key") in schema["sales"]["uniques"]
    assert "cost_total" not in schema["sales"]["columns"]
    assert schema["sale_items"]["columns"]["discount_allocated"]["nullable"] is False


@pytest.mark.parametrize(
    ("table", "check"),
    [
        ("business_memberships", "ck_business_memberships_role"),
        ("inventory_movements", "ck_inventory_movements_movement_type"),
        ("inventory_movements", "ck_inventory_movements_adjustment_has_reason"),
        ("sales", "ck_sales_status"),
        ("sales", "ck_sales_total_amount"),
        ("sales", "ck_sales_voided_has_reason"),
        ("payments", "ck_payments_method"),
        ("payments", "ck_payments_status"),
        ("payments", "ck_payments_provider"),
        ("payments", "ck_payments_amount_positive"),
        ("credit_transactions", "ck_credit_transactions_entry_type"),
        ("credit_transactions", "ck_credit_transactions_repayment_has_payment_method"),
        ("sale_items", "ck_sale_items_quantity_positive"),
        ("sale_items", "ck_sale_items_discount_allocated_within_line"),
        ("products", "ck_products_unit"),
        ("expenses", "ck_expenses_payment_method"),
        ("ai_messages", "ck_ai_messages_role"),
    ],
)
def test_check_constraints_exist(schema: dict[str, Any], table: str, check: str) -> None:
    assert check in schema[table]["checks"], sorted(schema[table]["checks"])


def test_ai_message_role_check_excludes_system(schema: dict[str, Any]) -> None:
    sqltext = schema["ai_messages"]["checks"]["ck_ai_messages_role"]
    assert "'user'" in sqltext and "'assistant'" in sqltext
    assert "system" not in sqltext


@pytest.mark.parametrize(
    ("table", "name", "columns", "unique"),
    [
        ("categories", "uq_categories_business_id_lower_name", ["business_id"], True),
        ("products", "uq_products_business_id_lower_name_active", ["business_id"], True),
        ("products", "uq_products_business_id_sku", ["business_id", "sku"], True),
        ("products", "uq_products_business_id_barcode", ["business_id", "barcode"], True),
        ("customers", "uq_customers_business_id_phone", ["business_id", "phone"], True),
        ("sales", "ix_sales_business_id_sold_at", ["business_id", "sold_at"], False),
        (
            "sales",
            "ix_sales_business_id_created_by_sold_at",
            ["business_id", "created_by", "sold_at"],
            False,
        ),
        ("sales", "ix_sales_business_id_customer_id", ["business_id", "customer_id"], False),
        (
            "inventory_movements",
            "ix_inventory_movements_business_id_product_id_occurred_at",
            ["business_id", "product_id", "occurred_at"],
            False,
        ),
        (
            "inventory_movements",
            "ix_inventory_movements_business_id_product_id_created_at",
            ["business_id", "product_id", "created_at"],
            False,
        ),
        (
            "credit_transactions",
            "ix_credit_transactions_business_id_customer_id_occurred_at",
            ["business_id", "customer_id", "occurred_at"],
            False,
        ),
        (
            "payments",
            "ix_payments_business_id_method_created_at",
            ["business_id", "method", "created_at"],
            False,
        ),
        (
            "ai_messages",
            "ix_ai_messages_business_id_role_created_at",
            ["business_id", "role", "created_at"],
            False,
        ),
        ("refresh_tokens", "ix_refresh_tokens_family_id", ["family_id"], False),
        (
            "mpesa_messages",
            "ix_mpesa_messages_business_id_occurred_at",
            ["business_id", "occurred_at"],
            False,
        ),
        (
            "mpesa_messages",
            "ix_mpesa_messages_business_id_status",
            ["business_id", "status"],
            False,
        ),
        ("mpesa_messages", "uq_mpesa_messages_business_id_code", ["business_id", "code"], True),
    ],
)
def test_documented_indexes_exist(
    schema: dict[str, Any], table: str, name: str, columns: list[str], unique: bool
) -> None:
    index = _index(schema, table, name)
    # Expression indexes report the expression separately; plain columns must match.
    assert [c for c in index["column_names"] if c is not None] == columns
    assert bool(index["unique"]) is unique


def test_partial_unique_indexes_have_their_predicates(schema: dict[str, Any]) -> None:
    assert "is_active" in str(
        _index(schema, "products", "uq_products_business_id_lower_name_active")["dialect_options"][
            "postgresql_where"
        ]
    )
    assert "sku IS NOT NULL" in str(
        _index(schema, "products", "uq_products_business_id_sku")["dialect_options"][
            "postgresql_where"
        ]
    )
    assert "phone IS NOT NULL" in str(
        _index(schema, "customers", "uq_customers_business_id_phone")["dialect_options"][
            "postgresql_where"
        ]
    )
    assert "code IS NOT NULL" in str(
        _index(schema, "mpesa_messages", "uq_mpesa_messages_business_id_code")["dialect_options"][
            "postgresql_where"
        ]
    )


def test_sales_period_index_is_descending_on_sold_at(schema: dict[str, Any]) -> None:
    index = _index(schema, "sales", "ix_sales_business_id_sold_at")
    assert index["column_sorting"] == {"sold_at": ("desc",)}
