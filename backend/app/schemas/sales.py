"""Sales and payments (docs/DATA_MAPPING.md §3.9-§3.11, PRD FR-F)."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import PaymentMethod, PaymentProvider, PaymentStatus, SaleStatus

MAX_LINES = 100
MAX_PAYMENT_LINES = 5


class SaleLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    # Optional override of the product's selling price (FR-F3); the default is recorded too.
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)


class PaymentLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    method: PaymentMethod
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    # Manually typed M-Pesa code; recorded, never verified (no Daraja integration).
    reference: str | None = Field(default=None, max_length=64)

    @field_validator("reference")
    @classmethod
    def _reference(cls, value: str | None) -> str | None:
        return value or None


class SaleCreateRequest(BaseModel):
    """Everything the server needs; totals are computed here, never taken from the client."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    lines: list[SaleLineRequest] = Field(min_length=1, max_length=MAX_LINES)
    payments: list[PaymentLineRequest] = Field(min_length=1, max_length=MAX_PAYMENT_LINES)
    customer_id: uuid.UUID | None = None
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    note: str | None = Field(default=None, max_length=255)
    # OWNER only, within the business's `sale_backdate_days` (FR-F8); default now.
    sold_at: datetime | None = None
    # OWNER only: proceed with a CREDIT sale over the customer's limit (FR-G5).
    credit_limit_override: bool = False

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("sold_at")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            msg = "sold_at must include a timezone offset"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _credit_needs_customer(self) -> "SaleCreateRequest":
        if (
            any(p.method is PaymentMethod.CREDIT for p in self.payments)
            and self.customer_id is None
        ):
            msg = "a CREDIT payment requires a customer"
            raise ValueError(msg)
        return self


class SaleVoidRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=255)


class SaleItemOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str  # snapshot at sale time
    quantity: Decimal
    unit_price: Decimal
    default_unit_price: Decimal
    line_total: Decimal
    discount_allocated: Decimal


class PaymentOut(BaseModel):
    id: uuid.UUID
    method: PaymentMethod
    amount: Decimal
    status: PaymentStatus
    reference: str | None
    provider: PaymentProvider


class SaleOut(BaseModel):
    id: uuid.UUID
    status: SaleStatus
    customer_id: uuid.UUID | None
    subtotal: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    note: str | None
    sold_at: datetime
    created_by: uuid.UUID
    created_at: datetime
    voided_at: datetime | None
    voided_by: uuid.UUID | None
    void_reason: str | None
    items: list[SaleItemOut]
    payments: list[PaymentOut]
