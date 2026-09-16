"""categories, products (docs/DATA_MAPPING.md §3.5-§3.6)."""

import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ProductUnit, enum_check, enum_column


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        # Lets products reference (category_id, business_id) with a composite tenant FK.
        UniqueConstraint("id", "business_id"),
        Index(
            "uq_categories_business_id_lower_name", "business_id", text("lower(name)"), unique=True
        ),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("id", "business_id"),
        ForeignKeyConstraint(
            ["category_id", "business_id"], ["categories.id", "categories.business_id"]
        ),
        enum_check("unit", ProductUnit, "unit"),
        CheckConstraint("selling_price >= 0", name="selling_price_non_negative"),
        CheckConstraint("cost_price IS NULL OR cost_price >= 0", name="cost_price_non_negative"),
        CheckConstraint("stock_quantity >= 0", name="stock_quantity_non_negative"),
        # Active product names are unique per business; archived duplicates may remain.
        Index(
            "uq_products_business_id_lower_name_active",
            "business_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index(
            "uq_products_business_id_sku",
            "business_id",
            "sku",
            unique=True,
            postgresql_where=text("sku IS NOT NULL"),
        ),
        Index(
            "uq_products_business_id_barcode",
            "business_id",
            "barcode",
            unique=True,
            postgresql_where=text("barcode IS NOT NULL"),
        ),
        Index(None, "business_id", "name"),
        Index(None, "category_id"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(60))
    barcode: Mapped[str | None] = mapped_column(String(64))
    unit: Mapped[ProductUnit] = mapped_column(
        enum_column(ProductUnit, 20), nullable=False, server_default=ProductUnit.PIECE.value
    )
    selling_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # NULL = unknown; such lines contribute 0 to COGS and are counted (PRD BR-16).
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # False for services: no movements, no stock validation, stock stays 0.
    track_inventory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Cache of the inventory_movements ledger (PRD BR-11); never written by the API directly.
    stock_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, server_default=text("0")
    )
    low_stock_threshold: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    category: Mapped[Category | None] = relationship(
        primaryjoin="and_(Product.category_id == Category.id, "
        "Product.business_id == Category.business_id)",
        foreign_keys="[Product.category_id, Product.business_id]",
        lazy="raise",
        viewonly=True,
    )
