"""Customers (docs/DATA_MAPPING.md §3.8, PRD FR-G1).

`balance` is read-only here: it is the cache of the credit ledger, moved only by
CHARGE / REPAYMENT / ADJUSTMENT / REVERSAL entries (sales and credit phases).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.identifiers import normalize_phone

MAX_NOTES_LENGTH = 2000


class CustomerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    # Optional; stored in E.164 (same normalisation as user phones) so one person is one row.
    phone: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=MAX_NOTES_LENGTH)
    credit_limit: Decimal | None = Field(default=None, max_digits=14, decimal_places=2, ge=0)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return normalize_phone(value) if value else None

    @field_validator("notes")
    @classmethod
    def _notes(cls, value: str | None) -> str | None:
        return value or None


class CustomerOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None
    notes: str | None
    credit_limit: Decimal | None
    balance: Decimal  # ledger cache; positive = owes the business
    is_active: bool
    created_at: datetime
    updated_at: datetime
