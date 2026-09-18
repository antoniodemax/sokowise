"""ai_conversations / ai_messages (docs/DATA_MAPPING.md §3.14-§3.15).

Conversations are private to the user who started them, inside their business: every
lookup is scoped by both `business_id` and `user_id`.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIConversation, AIMessage
from app.models.enums import AIMessageRole

MAX_CONVERSATIONS = 50
MAX_MESSAGES = 200


async def add_conversation(session: AsyncSession, conversation: AIConversation) -> AIConversation:
    session.add(conversation)
    await session.flush()
    return conversation


async def get_conversation(
    session: AsyncSession, *, business_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> AIConversation | None:
    stmt = select(AIConversation).where(
        AIConversation.business_id == business_id,
        AIConversation.user_id == user_id,
        AIConversation.id == conversation_id,
    )
    conversation: AIConversation | None = await session.scalar(stmt)
    return conversation


async def list_conversations(
    session: AsyncSession, *, business_id: uuid.UUID, user_id: uuid.UUID, limit: int
) -> list[AIConversation]:
    stmt = (
        select(AIConversation)
        .where(AIConversation.business_id == business_id, AIConversation.user_id == user_id)
        .order_by(AIConversation.updated_at.desc(), AIConversation.id)
        .limit(min(limit, MAX_CONVERSATIONS))
    )
    return list(await session.scalars(stmt))


async def add_message(session: AsyncSession, message: AIMessage) -> AIMessage:
    session.add(message)
    await session.flush()
    return message


async def list_messages(
    session: AsyncSession, *, business_id: uuid.UUID, conversation_id: uuid.UUID, limit: int
) -> list[AIMessage]:
    """Oldest first; when there are more than `limit`, the most recent ones."""
    stmt = (
        select(AIMessage)
        .where(AIMessage.business_id == business_id, AIMessage.conversation_id == conversation_id)
        .order_by(AIMessage.created_at.desc(), AIMessage.id.desc())
        .limit(min(limit, MAX_MESSAGES))
    )
    rows = list(await session.scalars(stmt))
    rows.reverse()
    return rows


async def count_user_messages_since(
    session: AsyncSession, *, business_id: uuid.UUID, since: datetime
) -> int:
    """Quota counting (PRD AI-8): user messages of the whole business since `since`."""
    stmt = select(func.count()).where(
        AIMessage.business_id == business_id,
        AIMessage.role == AIMessageRole.USER,
        AIMessage.created_at >= since,
    )
    return int(await session.scalar(stmt) or 0)


async def get_message(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    for_update: bool = False,
) -> AIMessage | None:
    stmt = select(AIMessage).where(
        AIMessage.business_id == business_id,
        AIMessage.conversation_id == conversation_id,
        AIMessage.id == message_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    message: AIMessage | None = await session.scalar(stmt)
    return message
