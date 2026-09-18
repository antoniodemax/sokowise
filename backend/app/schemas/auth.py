"""Request and response models for the authentication endpoints (docs/ARCHITECTURE.md §5).

Request models forbid unknown fields, so a client cannot smuggle `role`,
`business_id` or similar into a request and have it silently ignored: it is a
422 instead. Response models never expose `password_hash` or token hashes.
"""

import uuid
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.passwords import MAX_PASSWORD_LENGTH
from app.models.enums import BusinessType, MembershipRole
from app.schemas.identifiers import normalize_email, normalize_phone

MIN_PASSWORD_LENGTH = 8

# A short deny-list of the most common passwords (ARCHITECTURE §5.2). Compared
# case-insensitively. Not a substitute for length; just removes the worst choices.
COMMON_PASSWORDS = frozenset(
    {
        "12345678",
        "123456789",
        "1234567890",
        "password",
        "password1",
        "password123",
        "passw0rd",
        "qwerty123",
        "qwertyuiop",
        "iloveyou",
        "abc12345",
        "letmein1",
        "welcome1",
        "admin123",
        "sokowise",
        "sokowise1",
        "11111111",
        "00000000",
        "87654321",
        "football",
        "baseball",
        "sunshine",
        "princess",
        "trustno1",
        "1q2w3e4r",
        "123123123",
        "asdfghjk",
        "nairobi1",
        "kenya123",
        "mpesa123",
    }
)


def validate_new_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        msg = f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        raise ValueError(msg)
    if len(password) > MAX_PASSWORD_LENGTH:
        msg = f"password must be at most {MAX_PASSWORD_LENGTH} characters"
        raise ValueError(msg)
    if password.lower() in COMMON_PASSWORDS:
        msg = "password is too common; choose something less guessable"
        raise ValueError(msg)
    return password


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        msg = "timezone must be an IANA time zone name, e.g. Africa/Nairobi"
        raise ValueError(msg) from exc
    return value


class RegisterRequest(_StrictRequest):
    full_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=7, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    business_name: str = Field(min_length=1, max_length=120)
    business_type: BusinessType = BusinessType.GENERAL_SHOP
    timezone: str = Field(default="Africa/Nairobi", max_length=64)

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

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        return _validate_timezone(value)


class GoogleSignInRequest(_StrictRequest):
    # The ID token from Google Identity Services; verified server-side.
    credential: str = Field(min_length=20, max_length=4096)


class GoogleRegisterRequest(_StrictRequest):
    """Finish-up form after a Google sign-in with no account (ARCHITECTURE §5.1).

    The email and Google subject come from the signed `registration_token`, never from
    the form. There is no password: the account is Google-only until one is set.
    """

    registration_token: str = Field(min_length=20, max_length=4096)
    phone: str = Field(min_length=7, max_length=20)
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    business_name: str = Field(min_length=1, max_length=120)
    business_type: BusinessType = BusinessType.GENERAL_SHOP
    timezone: str = Field(default="Africa/Nairobi", max_length=64)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        return _validate_timezone(value)


class GoogleSignupPendingResponse(BaseModel):
    status: Literal["needs_registration"] = "needs_registration"
    registration_token: str
    email: str
    name: str | None


class PasswordResetRequestRequest(_StrictRequest):
    phone: str = Field(min_length=7, max_length=20)


class PasswordResetConfirmRequest(_StrictRequest):
    phone: str = Field(min_length=7, max_length=20)
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")
    new_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _password(cls, value: str) -> str:
        return validate_new_password(value)


class MessageResponse(BaseModel):
    message: str


class LoginRequest(_StrictRequest):
    # Phone (E.164 or Kenyan local form) or email; normalised the same way as at registration.
    identifier: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class ChangePasswordRequest(_StrictRequest):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _new_password(cls, value: str) -> str:
        return validate_new_password(value)

    @model_validator(mode="after")
    def _must_differ(self) -> "ChangePasswordRequest":
        if self.new_password == self.current_password:
            msg = "new password must differ from the current password"
            raise ValueError(msg)
        return self


class UserOut(BaseModel):
    id: uuid.UUID
    full_name: str
    phone: str
    email: str | None
    must_change_password: bool


class BusinessOut(BaseModel):
    id: uuid.UUID
    name: str
    business_type: BusinessType
    currency: str
    timezone: str
    is_active: bool


class MeResponse(BaseModel):
    user: UserOut
    business: BusinessOut
    role: MembershipRole
    # Whether this user may open the operator dashboard (`PLATFORM_ADMIN_PHONES`). The
    # frontend only uses it to show the route; the backend re-checks on every request.
    is_platform_admin: bool = False


class SessionResponse(MeResponse):
    """Returned by register, login, refresh and change-password.

    The refresh token is not in the body: it travels only in the HttpOnly cookie.
    """

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — a scheme name, not a secret
    expires_in: int  # seconds until the access token expires
