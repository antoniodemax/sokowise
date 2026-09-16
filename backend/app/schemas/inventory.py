"""Inventory operations and movement history (docs/DATA_MAPPING.md §3.7, PRD FR-E)."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import MovementType


def _clean(value: str | None) -> str | None:
    return value or None


class RestockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_cost: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    supplier_name: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=255)
    # FR-E5: the product's current cost_price may be set to this restock's unit cost.
    update_cost_price: bool = False

    @field_validator("supplier_name", "reason")
    @classmethod
    def _optional(cls, value: str | None) -> str | None:
        return _clean(value)


class AdjustmentRequest(BaseModel):
    """Signed stock correction with a reason (BR-4). Stock never goes below zero."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_id: uuid.UUID
    quantity_delta: Decimal = Field(max_digits=12, decimal_places=3)
    reason: str = Field(min_length=1, max_length=255)

    @field_validator("quantity_delta")
    @classmethod
    def _non_zero(cls, value: Decimal) -> Decimal:
        if value == 0:
            msg = "quantity_delta must not be zero"
            raise ValueError(msg)
        return value


class InitialStockRequest(BaseModel):
    """Opening stock for a tracked product that has no movements yet (FR-D6)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_cost: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class RecomputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # False = report only; True = rewrite every cached stock that disagrees with the ledger.
    apply: bool = False


class MovementOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    movement_type: MovementType
    quantity_delta: Decimal
    quantity_after: Decimal  # running balance in posting order, not by occurred_at
    unit_cost: Decimal | None
    total_cost: Decimal | None
    sale_id: uuid.UUID | None
    supplier_name: str | None
    reason: str | None
    occurred_at: datetime
    created_at: datetime
    created_by: uuid.UUID


class LowStockProductOut(BaseModel):
    product_id: uuid.UUID
    name: str
    sku: str | None
    unit: str
    stock_quantity: Decimal
    threshold: Decimal  # the product's own threshold or the business default


class StockDiscrepancyOut(BaseModel):
    product_id: uuid.UUID
    cached_stock: Decimal
    ledger_stock: Decimal
    repaired: bool


class RecomputeResponse(BaseModel):
    products_checked: int
    discrepancies: list[StockDiscrepancyOut]
    applied: bool
