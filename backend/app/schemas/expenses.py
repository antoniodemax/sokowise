"""Expenses (docs/DATA_MAPPING.md §3.13, PRD FR-H). Money as Decimal strings."""

import re
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import MoneyReceivedMethod

# The suggested list (DATA_MAPPING §3.13); free text is allowed on top of it.
SUGGESTED_CATEGORIES = (
    "RENT",
    "TRANSPORT",
    "UTILITIES",
    "AIRTIME",
    "SALARIES",
    "LICENSES",
    "OTHER",
)
_WHITESPACE = re.compile(r"\s+")


def normalize_category(value: str) -> str:
    """Trimmed, single-spaced, upper-case — so "rent" and "Rent " group as RENT."""
    return _WHITESPACE.sub(" ", value.strip()).upper()


def _clean(value: str | None) -> str | None:
    return value or None


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        msg = "incurred_at must include a timezone offset"
        raise ValueError(msg)
    return value


class ExpenseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    category: str = Field(min_length=1, max_length=60)
    payment_method: MoneyReceivedMethod
    reference: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=255)
    # When the money was spent; defaults to now. Past dates are fine, the future is not.
    incurred_at: datetime | None = None

    @field_validator("category")
    @classmethod
    def _category(cls, value: str) -> str:
        normalized = normalize_category(value)
        if not normalized:
            msg = "category must not be blank"
            raise ValueError(msg)
        return normalized

    @field_validator("reference", "note")
    @classmethod
    def _optional(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("incurred_at")
    @classmethod
    def _incurred_at(cls, value: datetime | None) -> datetime | None:
        return _aware(value)


class ExpenseUpdateRequest(BaseModel):
    """PATCH: only fields present change; explicit null clears reference/note."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    category: str | None = Field(default=None, min_length=1, max_length=60)
    payment_method: MoneyReceivedMethod | None = None
    reference: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=255)
    incurred_at: datetime | None = None

    @field_validator("category")
    @classmethod
    def _category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_category(value)
        if not normalized:
            msg = "category must not be blank"
            raise ValueError(msg)
        return normalized

    @field_validator("reference", "note")
    @classmethod
    def _optional(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("incurred_at")
    @classmethod
    def _incurred_at(cls, value: datetime | None) -> datetime | None:
        return _aware(value)

    @model_validator(mode="after")
    def _something_to_change(self) -> "ExpenseUpdateRequest":
        if not self.model_fields_set:
            msg = "provide at least one field to change"
            raise ValueError(msg)
        for name in ("amount", "category", "payment_method", "incurred_at"):
            if name in self.model_fields_set and getattr(self, name) is None:
                msg = f"{name} cannot be null"
                raise ValueError(msg)
        return self


class ExpenseOut(BaseModel):
    id: uuid.UUID
    amount: Decimal
    category: str
    payment_method: MoneyReceivedMethod
    reference: str | None
    note: str | None
    incurred_at: datetime
    deleted_at: datetime | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ExpenseCategoriesOut(BaseModel):
    suggested: list[str]  # the fixed list plus every category this business has used
