"""Business profile and settings (docs/DATA_MAPPING.md §3.1, PRD FR-A3)."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import BusinessType
from app.schemas.identifiers import normalize_phone


def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        msg = "timezone must be an IANA time zone name, e.g. Africa/Nairobi"
        raise ValueError(msg) from exc
    return value


class BusinessSettings(BaseModel):
    """The owner-editable keys of `businesses.settings`. Nothing else is accepted."""

    model_config = ConfigDict(extra="forbid")

    staff_can_restock: bool = False
    sale_backdate_days: int = Field(default=7, ge=0, le=90)
    low_stock_default_threshold: int = Field(default=5, ge=0, le=100_000)


class BusinessUpdateRequest(BaseModel):
    """PATCH semantics: only fields present are changed; `settings` replaces the whole object."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    business_type: BusinessType | None = None
    phone: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=255)
    timezone: str | None = Field(default=None, max_length=64)
    settings: BusinessSettings | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        return normalize_phone(value) if value else None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        return validate_timezone(value) if value is not None else None


class BusinessDetail(BaseModel):
    id: uuid.UUID
    name: str
    business_type: BusinessType
    phone: str | None
    address: str | None
    currency: str
    timezone: str
    settings: BusinessSettings
    is_active: bool
    created_at: datetime
