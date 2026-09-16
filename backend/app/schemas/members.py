"""Business members (users through their membership; docs/DATA_MAPPING.md §3.3, PRD FR-C)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.passwords import MAX_PASSWORD_LENGTH
from app.models.enums import MembershipRole
from app.schemas.auth import validate_new_password
from app.schemas.identifiers import normalize_email, normalize_phone


class StaffCreateRequest(BaseModel):
    """Creates a STAFF user (PRD FR-C1). The role is fixed; there is no field for it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=7, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    # Initial password; the user must replace it at first login.
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return normalize_email(value) if value else None

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        return validate_new_password(value)


class MemberUpdateRequest(BaseModel):
    """Change a member's role and/or (de)activate their membership."""

    model_config = ConfigDict(extra="forbid")

    role: MembershipRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> "MemberUpdateRequest":
        if self.role is None and self.is_active is None:
            msg = "provide role and/or is_active"
            raise ValueError(msg)
        return self


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        return validate_new_password(value)


class MemberOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    phone: str
    email: str | None
    role: MembershipRole
    is_active: bool  # the membership, i.e. access to this business
    must_change_password: bool
    last_login_at: datetime | None
    joined_at: datetime
