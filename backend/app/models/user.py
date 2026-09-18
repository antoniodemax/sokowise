"""users, business_memberships, refresh_tokens (docs/DATA_MAPPING.md §3.2-§3.4).

Only the tables. Password hashing, tokens and login logic arrive in Phase 3.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.business import Business
from app.models.enums import MembershipRole, enum_check, enum_column


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # NULL for an account created through Google sign-in that has not set a password yet;
    # password login never succeeds for it (DATA_MAPPING §3.2).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # Google's stable subject id once the account is linked to a Google identity.
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Set when an OWNER creates a STAFF user or resets their password (DATA_MAPPING §3.2).
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list["BusinessMembership"]] = relationship(
        back_populates="user", lazy="raise"
    )


class BusinessMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "business_memberships"
    __table_args__ = (
        UniqueConstraint("business_id", "user_id"),
        enum_check("role", MembershipRole, "role"),
        Index(None, "user_id"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    role: Mapped[MembershipRole] = mapped_column(enum_column(MembershipRole, 20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    business: Mapped[Business] = relationship(lazy="raise")
    user: Mapped[User] = relationship(back_populates="memberships", lazy="raise")


class RefreshToken(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index(None, "family_id"), Index(None, "user_id"))

    # Shared by every token in one login session's rotation chain; equals the first
    # token's id. Reuse of a revoked token revokes the whole family (DATA_MAPPING §3.4).
    family_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("refresh_tokens.id")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(45))


class PasswordResetCode(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A one-time 6-digit code sent by SMS for self-service password reset (DATA_MAPPING §3.20).

    Only the SHA-256 of `user_id:code` is stored. A code is live while `used_at` is NULL,
    `expires_at` is in the future and `attempts` is under the limit; the confirm step
    consumes it in one UPDATE, like refresh-token rotation.
    """

    __tablename__ = "password_reset_codes"
    __table_args__ = (Index(None, "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(45))
