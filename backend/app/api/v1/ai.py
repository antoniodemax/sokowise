"""AI copilot endpoints (docs/ARCHITECTURE.md §6; PRD FR-J, AI-14: OWNER-only)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import AINotConfiguredError
from app.ai.provider import AIProvider
from app.ai.service import AIService, Quota
from app.api.deps import enforce_rate_limit, get_settings_dep, require_owner
from app.core.config import Settings
from app.core.context import BusinessContext
from app.db.session import get_session
from app.models import AIConversation, AIMessage
from app.repositories.ai import MAX_CONVERSATIONS
from app.schemas.ai import (
    AskResponse,
    ConversationCreateRequest,
    ConversationDetailOut,
    ConversationOut,
    MessageCreateRequest,
    MessageOut,
    QuotaOut,
    ToolCallOut,
)

router = APIRouter(prefix="/ai", tags=["ai"])

OwnerCtx = Annotated[BusinessContext, Depends(require_owner)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_ai_provider(request: Request) -> AIProvider:
    provider: AIProvider | None = getattr(request.app.state, "ai_provider", None)
    if provider is None:
        raise AINotConfiguredError("The assistant is not set up on this server yet.")
    return provider


def get_ai_service(
    provider: Annotated[AIProvider, Depends(get_ai_provider)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AIService:
    return AIService(provider, settings)


ServiceDep = Annotated[AIService, Depends(get_ai_service)]


def conversation_out(conversation: AIConversation) -> ConversationOut:
    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _tool_call_out(call: dict[str, object]) -> ToolCallOut:
    raw_input = call.get("input")
    duration = call.get("duration_ms")
    return ToolCallOut(
        name=str(call.get("name", "")),
        input={str(k): v for k, v in raw_input.items()} if isinstance(raw_input, dict) else {},
        ok=bool(call.get("ok", False)),
        duration_ms=int(duration) if isinstance(duration, int | float) else 0,
    )


def message_out(message: AIMessage) -> MessageOut:
    return MessageOut(
        id=message.id,
        role=message.role.value,
        content=message.content,
        tool_calls=[_tool_call_out(call) for call in (message.tool_calls or [])] or None,
        stop_reason=message.stop_reason,
        created_at=message.created_at,
    )


def quota_out(quota: Quota) -> QuotaOut:
    return QuotaOut(
        daily_limit=quota.daily_limit,
        daily_used=quota.daily_used,
        monthly_limit=quota.monthly_limit,
        monthly_used=quota.monthly_used,
        resets_at=quota.resets_at,
    )


@router.get("/quota", response_model=QuotaOut)
async def quota(ctx: OwnerCtx, session: SessionDep, service: ServiceDep) -> QuotaOut:
    return quota_out(await service.quota(session, ctx))


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreateRequest, ctx: OwnerCtx, session: SessionDep, service: ServiceDep
) -> ConversationOut:
    conversation = await service.create_conversation(session, ctx, title=body.title)
    return conversation_out(conversation)


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    ctx: OwnerCtx,
    session: SessionDep,
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=MAX_CONVERSATIONS)] = MAX_CONVERSATIONS,
) -> list[ConversationOut]:
    return [
        conversation_out(c) for c in await service.list_conversations(session, ctx, limit=limit)
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation(
    conversation_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep, service: ServiceDep
) -> ConversationDetailOut:
    conversation, messages = await service.get_conversation(session, ctx, conversation_id)
    return ConversationDetailOut(
        **conversation_out(conversation).model_dump(), messages=[message_out(m) for m in messages]
    )


@router.post("/conversations/{conversation_id}/messages", response_model=AskResponse)
async def send_message(
    conversation_id: uuid.UUID,
    body: MessageCreateRequest,
    request: Request,
    ctx: OwnerCtx,
    session: SessionDep,
    service: ServiceDep,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AskResponse:
    enforce_rate_limit(
        request, scope="ai", key=str(ctx.user_id), limit=settings.rate_limit_ai_messages_per_minute
    )
    result = await service.ask(session, ctx, conversation_id, body.content)
    return AskResponse(
        conversation_id=result.conversation.id,
        user_message=message_out(result.user_message),
        assistant_message=message_out(result.assistant_message),
        quota=quota_out(result.quota),
    )
