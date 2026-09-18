"""Categories and products (docs/DATA_MAPPING.md §3.5-§3.6, PRD FR-D).

Money is `Decimal` with two places (NUMERIC(14,2)); quantities have three
(NUMERIC(12,3)). JSON responses carry them as strings so no client is tempted
into floating point.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import ProductUnit

# Field bounds mirror the columns (14,2 money; 12,3 quantities): Pydantic rejects extra
# digits instead of the database rounding them.


def _clean_optional_text(value: str | None) -> str | None:
    """Strip; treat an empty string as "not provided" so it clears the field."""
    if value is None:
        return None
    value = value.strip()
    return value or None


# --- categories ---------------------------------------------------------------------


class CategoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=60)


class CategoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=60)


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime


# --- products -----------------------------------------------------------------------


class _ProductFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("sku", "barcode", check_fields=False)
    @classmethod
    def _optional_code(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)


class ProductCreateRequest(_ProductFields):
    name: str = Field(min_length=1, max_length=120)
    category_id: uuid.UUID | None = None
    sku: str | None = Field(default=None, max_length=60)
    barcode: str | None = Field(default=None, max_length=64)
    unit: ProductUnit = ProductUnit.PIECE
    selling_price: Decimal = Field(max_digits=14, decimal_places=2, ge=0)
    cost_price: Decimal | None = Field(default=None, max_digits=14, decimal_places=2, ge=0)
    track_inventory: bool = True
    low_stock_threshold: Decimal | None = Field(default=None, max_digits=12, decimal_places=3, ge=0)
    # PRD FR-D6: when present, an INITIAL movement is written with the product atomically.
    opening_stock: Decimal | None = Field(default=None, max_digits=12, decimal_places=3, gt=0)
    opening_unit_cost: Decimal | None = Field(default=None, max_digits=14, decimal_places=2, ge=0)

    @model_validator(mode="after")
    def _opening_stock_rules(self) -> "ProductCreateRequest":
        if self.opening_stock is not None and not self.track_inventory:
            msg = "opening_stock requires track_inventory=true; untracked products hold no stock"
            raise ValueError(msg)
        if self.opening_stock is None and self.opening_unit_cost is not None:
            msg = "opening_unit_cost needs opening_stock"
            raise ValueError(msg)
        if (
            self.opening_stock is not None
            and self.opening_unit_cost is None
            and self.cost_price is None
        ):
            # INITIAL movements carry a unit cost (DATA_MAPPING §3.7); cost_price is the default.
            msg = "opening_unit_cost is required when cost_price is unknown"
            raise ValueError(msg)
        return self


class ProductUpdateRequest(_ProductFields):
    """PATCH: fields present are changed; explicit null clears an optional field."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    category_id: uuid.UUID | None = None
    sku: str | None = Field(default=None, max_length=60)
    barcode: str | None = Field(default=None, max_length=64)
    unit: ProductUnit | None = None
    selling_price: Decimal | None = Field(default=None, max_digits=14, decimal_places=2, ge=0)
    cost_price: Decimal | None = Field(default=None, max_digits=14, decimal_places=2, ge=0)
    track_inventory: bool | None = None
    low_stock_threshold: Decimal | None = Field(default=None, max_digits=12, decimal_places=3, ge=0)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _no_nulls_for_required_fields(self) -> "ProductUpdateRequest":
        for name in ("name", "unit", "selling_price", "track_inventory", "is_active"):
            if name in self.model_fields_set and getattr(self, name) is None:
                msg = f"{name} cannot be null"
                raise ValueError(msg)
        if not self.model_fields_set:
            msg = "provide at least one field to change"
            raise ValueError(msg)
        return self


class ProductOut(BaseModel):
    id: uuid.UUID
    name: str
    category_id: uuid.UUID | None
    sku: str | None
    barcode: str | None
    unit: ProductUnit
    selling_price: Decimal
    cost_price: Decimal | None
    track_inventory: bool
    # The ledger cache (BR-11); always 0 for untracked products.
    stock_quantity: Decimal
    low_stock_threshold: Decimal | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductBulkCreateRequest(BaseModel):
    """The setup wizard: many products in one transaction (PRD FR-N)."""

    model_config = ConfigDict(extra="forbid")

    items: list[ProductCreateRequest] = Field(min_length=1, max_length=100)


class StarterItemOut(BaseModel):
    name: str
    selling_price: Decimal
    cost_price: Decimal | None
    unit: ProductUnit
    track_inventory: bool
