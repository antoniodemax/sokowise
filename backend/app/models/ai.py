"""ai_conversations, ai_messages (docs/DATA_MAPPING.md §3.14-§3.15).

Tables only; the Claude integration is Phase 9. The system prompt is built per
request and never stored, so `role` is only `user` or `assistant`.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AIMessageRole, ProposalStatus, enum_check, enum_column


class AIConversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        UniqueConstraint("id", "business_id"),
        Index(None, "business_id", "user_id"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    # Conversations are private to the user who started them.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(120))


class AIMessage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "business_id"],
            ["ai_conversations.id", "ai_conversations.business_id"],
        ),
        enum_check("role", AIMessageRole, "role"),
        enum_check("proposal_status", ProposalStatus, "proposal_status"),
        CheckConstraint(
            "(proposal IS NULL) = (proposal_status IS NULL)", name="proposal_has_status"
        ),
        # Quotas count role = 'user' rows per business.
        Index(None, "business_id", "role", "created_at"),
        Index(None, "conversation_id", "created_at"),
    )

    business_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    role: Mapped[AIMessageRole] = mapped_column(enum_column(AIMessageRole, 20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # [{name, input, output_summary, duration_ms}] with bounded outputs.
    tool_calls: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(60))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer)
    stop_reason: Mapped[str | None] = mapped_column(String(30))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    # A proposed action (PRD FR-J7): {kind, payload}. Data the model returned, never
    # executed by itself; `services.ai_actions.confirm` applies the owner's confirmed payload.
    # none_as_null: a message without a proposal stores SQL NULL, not the JSON literal null.
    proposal: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    proposal_status: Mapped[ProposalStatus | None] = mapped_column(enum_column(ProposalStatus, 10))
    proposal_entity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    proposal_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
