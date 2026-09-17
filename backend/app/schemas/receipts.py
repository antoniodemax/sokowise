"""Supplier receipt request/response shapes (docs/ARCHITECTURE.md §6.7)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ReceiptLineReview, ReceiptMatchStatus, ReceiptStatus

MAX_CONFIRM_LINES = 60


class ReceiptLineOut(BaseModel):
    id: uuid.UUID
    position: int
    extracted_name: str
    extracted_sku: str | None
    extracted_quantity: Decimal
    extracted_unit_cost: Decimal
    extracted_line_total: Decimal | None
    confidence: Decimal | None
    warnings: list[str]
    match_status: ReceiptMatchStatus
    matched_product_id: uuid.UUID | None
    candidate_product_ids: list[uuid.UUID]
    review_status: ReceiptLineReview
    final_product_id: uuid.UUID | None
    final_quantity: Decimal | None
    final_unit_cost: Decimal | None
    movement_id: uuid.UUID | None


class ReceiptSummaryOut(BaseModel):
    id: uuid.UUID
    status: ReceiptStatus
    original_filename: str | None
    mime_type: str
    size_bytes: int
    supplier_name: str | None
    receipt_number: str | None
    receipt_date: date | None
    currency: str | None
    extracted_subtotal: Decimal | None
    extracted_total: Decimal | None
    extraction_provider: str | None
    extraction_model: str | None
    extraction_error: str | None
    warnings: list[str]
    line_count: int
    extracted_at: datetime | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReceiptOut(ReceiptSummaryOut):
    lines: list[ReceiptLineOut]


class ConfirmLine(BaseModel):
    """The owner's final decision for one extracted line."""

    model_config = ConfigDict(extra="forbid")

    line_id: uuid.UUID
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_cost: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    update_cost_price: bool = False


class ReceiptConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    lines: list[ConfirmLine] = Field(min_length=1, max_length=MAX_CONFIRM_LINES)
    supplier_name: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=255)

    @field_validator("lines")
    @classmethod
    def unique_lines(cls, lines: list[ConfirmLine]) -> list[ConfirmLine]:
        if len({line.line_id for line in lines}) != len(lines):
            msg = "each receipt line may be confirmed once"
            raise ValueError(msg)
        return lines


class ReceiptConfirmOut(BaseModel):
    receipt: ReceiptOut
    movements_created: int
