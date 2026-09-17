"""Customer credit ledger: repayments, adjustments, ledger and debtors (PRD FR-G2-G5)."""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import CreditEntryType, MoneyReceivedMethod


class AdjustmentDirection(StrEnum):
    INCREASE = "INCREASE"  # the customer owes more
    DECREASE = "DECREASE"  # the customer owes less


class RepaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    payment_method: MoneyReceivedMethod
    # e.g. the M-Pesa confirmation code; recorded, never verified (no Daraja integration).
    reference: str | None = Field(default=None, max_length=64)
    # PRD BR-7 allows a balance below zero ("credit in favour"), but only on purpose: a
    # repayment larger than the debt is a 409 unless the caller says the customer prepaid.
    allow_overpayment: bool = False

    @field_validator("reference")
    @classmethod
    def _reference(cls, value: str | None) -> str | None:
        return value or None


class AdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    direction: AdjustmentDirection
    reason: str = Field(min_length=1, max_length=255)


class LedgerEntryOut(BaseModel):
    id: uuid.UUID
    entry_type: CreditEntryType
    # Signed effect on the balance: CHARGE +, REPAYMENT -, REVERSAL -, ADJUSTMENT ±.
    amount: Decimal
    balance_after: Decimal
    payment_method: MoneyReceivedMethod | None
    reference: str | None
    reason: str | None
    sale_id: uuid.UUID | None
    occurred_at: datetime
    created_at: datetime
    created_by: uuid.UUID


class LedgerResponse(BaseModel):
    customer_id: uuid.UUID
    balance: Decimal  # positive = owes the business; negative = credit in favour
    credit_limit: Decimal | None
    entries: list[LedgerEntryOut]  # newest first


class DebtorOut(BaseModel):
    customer_id: uuid.UUID
    name: str
    phone: str | None
    balance: Decimal
    credit_limit: Decimal | None
    oldest_unpaid_charge_at: datetime | None


class BalanceRecomputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # False = report only; True = rewrite every cached balance that disagrees with the ledger.
    apply: bool = False


class BalanceDiscrepancyOut(BaseModel):
    customer_id: uuid.UUID
    cached_balance: Decimal
    ledger_balance: Decimal
    repaired: bool


class BalanceRecomputeResponse(BaseModel):
    customers_checked: int
    discrepancies: list[BalanceDiscrepancyOut]
    applied: bool
