"""Request/response models for `/api/v1/mpesa` (docs/ARCHITECTURE.md §7)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import MpesaMessageStatus, SmsKind


class MpesaPasteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # One confirmation SMS. Long enough for the longest Safaricom template plus a footer.
    text: str = Field(min_length=10, max_length=1000)


class MpesaMatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_id: uuid.UUID | None = None
    credit_transaction_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def exactly_one_target(self) -> "MpesaMatchRequest":
        if (self.payment_id is None) == (self.credit_transaction_id is None):
            msg = "Give exactly one of payment_id or credit_transaction_id"
            raise ValueError(msg)
        return self


class MpesaRepaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: uuid.UUID
    allow_overpayment: bool = False


class MpesaIgnoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str | None = Field(default=None, max_length=255)


class CandidatePaymentOut(BaseModel):
    payment_id: uuid.UUID
    sale_id: uuid.UUID
    amount: Decimal
    reference: str | None
    sold_at: datetime


class CandidateCustomerOut(BaseModel):
    customer_id: uuid.UUID
    name: str
    phone: str | None
    balance: Decimal


class CandidatesOut(BaseModel):
    payments: list[CandidatePaymentOut]
    customers: list[CandidateCustomerOut]


class MpesaMessageOut(BaseModel):
    id: uuid.UUID
    status: MpesaMessageStatus
    code: str | None
    amount: Decimal | None
    kind: SmsKind | None
    sender_name: str | None
    sender_phone_masked: str | None
    account_reference: str | None
    occurred_at: datetime | None
    raw_text: str
    payment_id: uuid.UUID | None
    sale_id: uuid.UUID | None
    credit_transaction_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    matched_at: datetime | None
    ignored_at: datetime | None
    ignore_reason: str | None
    created_at: datetime
    # Suggestions for an UNMATCHED row; never applied automatically.
    candidates: CandidatesOut | None = None


class ReconciliationOut(BaseModel):
    date: date
    received_count: int
    received_total: Decimal
    matched_count: int
    matched_total: Decimal
    unmatched_count: int
    unmatched_total: Decimal
    ignored_count: int
    unparsed_count: int
    # M-Pesa money the app has recorded for the same local day: tenders + repayments.
    recorded_in_app: Decimal
