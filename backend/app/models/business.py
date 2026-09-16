"""businesses — the tenant (docs/DATA_MAPPING.md §3.1)."""

from sqlalchemy import Boolean, String, text
from sqlalchemy.dialects.postgresql import CHAR, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import BusinessType, enum_check, enum_column


class Business(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "businesses"
    __table_args__ = (enum_check("business_type", BusinessType, "business_type"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    business_type: Mapped[BusinessType] = mapped_column(
        enum_column(BusinessType, 40), nullable=False
    )
    phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, server_default="KES")
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Africa/Nairobi"
    )
    # Owner-editable settings validated by a Pydantic model in Phase 4. AI quotas are
    # deliberately not stored here (DATA_MAPPING §3.1).
    settings: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
