"""AI copilot request/response shapes (docs/ARCHITECTURE.md §6)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MAX_MESSAGE_CHARS = 2000


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=120)


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class ToolCallOut(BaseModel):
    name: str
    input: dict[str, object]
    ok: bool
    duration_ms: int


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    tool_calls: list[ToolCallOut] | None
    stop_reason: str | None
    created_at: datetime


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]


class MessageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class QuotaOut(BaseModel):
    """Server-side limits (PRD AI-8); shown to the owner, never editable by them."""

    daily_limit: int
    daily_used: int
    monthly_limit: int
    monthly_used: int
    resets_at: datetime  # next local midnight in the business timezone


class AskResponse(BaseModel):
    conversation_id: uuid.UUID
    user_message: MessageOut
    assistant_message: MessageOut
    quota: QuotaOut
