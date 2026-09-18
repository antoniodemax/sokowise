"""The copilot orchestrator (docs/ARCHITECTURE.md §6.1).

    persist user message → call the model → run allowlisted tools in a read-only
    savepoint → repeat (bounded) → persist the assistant message.

Tenant identity comes from `BusinessContext` only; the model never sees or sends a
business id. A provider failure leaves the user message stored and no assistant
message; nothing is ever invented on the model's behalf.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import AIQuotaExceededError, AIUnavailableError
from app.ai.prompts import SYSTEM_PROMPT, volatile_context
from app.ai.proposals import PROPOSAL_TOOLS, ProposalKind, StoredProposal, validate_proposal
from app.ai.provider import AIProvider, ProviderResponse, ToolCall, Usage
from app.ai.tools import TOOLS, ToolInputError, serialise_result, tool_definitions
from app.core.config import Settings
from app.core.context import BusinessContext
from app.core.errors import NotFoundError
from app.db.session import transaction
from app.models import AIConversation, AIMessage
from app.models.enums import AIMessageRole, ProposalStatus
from app.repositories import ai as ai_repo
from app.repositories import businesses as business_repo
from app.repositories import users as user_repo

logger = logging.getLogger(__name__)

# Shown when the model proposed an action without any text of its own.
_PROPOSAL_FALLBACK_TEXT: dict[ProposalKind | None, str] = {
    ProposalKind.PRODUCT: "I prepared a new product. Check it and tap Confirm to add it.",
    ProposalKind.SALE: "I prepared this sale. Check it and tap Confirm to record it.",
    ProposalKind.REPAYMENT: "I prepared this deni payment. Check it and tap Confirm to record it.",
    ProposalKind.RESTOCK: "I prepared this restock. Check it and tap Confirm to add the stock.",
    None: "",
}

OUTPUT_SUMMARY_CHARS = 500


@dataclass(frozen=True, slots=True)
class Quota:
    daily_limit: int
    daily_used: int
    monthly_limit: int
    monthly_used: int
    resets_at: datetime


@dataclass(frozen=True, slots=True)
class AskResult:
    conversation: AIConversation
    user_message: AIMessage
    assistant_message: AIMessage
    quota: Quota


def _local_day_start(timezone: str, now: datetime) -> datetime:
    tz = ZoneInfo(timezone)
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def _local_month_start(timezone: str, now: datetime) -> datetime:
    tz = ZoneInfo(timezone)
    local = now.astimezone(tz)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


class AIService:
    def __init__(self, provider: AIProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    # --- conversations ---------------------------------------------------------------------

    async def create_conversation(
        self, session: AsyncSession, ctx: BusinessContext, *, title: str | None
    ) -> AIConversation:
        conversation = AIConversation(
            business_id=ctx.business_id, user_id=ctx.user_id, title=title or None
        )
        async with transaction(session):
            await ai_repo.add_conversation(session, conversation)
        return conversation

    async def list_conversations(
        self, session: AsyncSession, ctx: BusinessContext, *, limit: int
    ) -> list[AIConversation]:
        return await ai_repo.list_conversations(
            session, business_id=ctx.business_id, user_id=ctx.user_id, limit=limit
        )

    async def get_conversation(
        self, session: AsyncSession, ctx: BusinessContext, conversation_id: uuid.UUID
    ) -> tuple[AIConversation, list[AIMessage]]:
        conversation = await ai_repo.get_conversation(
            session,
            business_id=ctx.business_id,
            user_id=ctx.user_id,
            conversation_id=conversation_id,
        )
        if conversation is None:
            raise NotFoundError("Conversation not found")
        messages = await ai_repo.list_messages(
            session,
            business_id=ctx.business_id,
            conversation_id=conversation.id,
            limit=ai_repo.MAX_MESSAGES,
        )
        return conversation, messages

    # --- quota -----------------------------------------------------------------------------

    async def quota(
        self, session: AsyncSession, ctx: BusinessContext, *, now: datetime | None = None
    ) -> Quota:
        now = now or datetime.now(UTC)
        day_start = _local_day_start(ctx.timezone, now)
        month_start = _local_month_start(ctx.timezone, now)
        daily_used = await ai_repo.count_user_messages_since(
            session, business_id=ctx.business_id, since=day_start
        )
        monthly_used = await ai_repo.count_user_messages_since(
            session, business_id=ctx.business_id, since=month_start
        )
        return Quota(
            daily_limit=self._settings.ai_daily_message_limit,
            daily_used=daily_used,
            monthly_limit=self._settings.ai_monthly_message_limit,
            monthly_used=monthly_used,
            resets_at=day_start + timedelta(days=1),
        )

    def _enforce_quota(self, quota: Quota, ctx: BusinessContext, now: datetime) -> None:
        if quota.daily_used >= quota.daily_limit:
            raise AIQuotaExceededError(
                f"You have used today's {quota.daily_limit} questions. "
                "The limit resets at midnight.",
                details={
                    "scope": "day",
                    "limit": quota.daily_limit,
                    "used": quota.daily_used,
                    "resets_at": quota.resets_at.isoformat(),
                },
                headers={"Retry-After": str(max(1, int((quota.resets_at - now).total_seconds())))},
            )
        if quota.monthly_used >= quota.monthly_limit:
            month_reset = (
                (
                    _local_month_start(ctx.timezone, now).astimezone(ZoneInfo(ctx.timezone))
                    + timedelta(days=32)
                )
                .replace(day=1)
                .astimezone(UTC)
            )
            raise AIQuotaExceededError(
                f"You have used this month's {quota.monthly_limit} questions. "
                "The limit resets next month.",
                details={
                    "scope": "month",
                    "limit": quota.monthly_limit,
                    "used": quota.monthly_used,
                    "resets_at": month_reset.isoformat(),
                },
                headers={"Retry-After": str(max(1, int((month_reset - now).total_seconds())))},
            )

    # --- ask -------------------------------------------------------------------------------

    async def ask(
        self,
        session: AsyncSession,
        ctx: BusinessContext,
        conversation_id: uuid.UUID,
        content: str,
        *,
        now: datetime | None = None,
    ) -> AskResult:
        now = now or datetime.now(UTC)
        conversation, history = await self.get_conversation(session, ctx, conversation_id)
        content = content.strip()

        # A retry of a question whose answer failed reuses the stored user message: no
        # duplicate row and no second quota hit.
        reuse = (
            history[-1]
            if history and history[-1].role == AIMessageRole.USER and history[-1].content == content
            else None
        )
        if reuse is None:
            quota = await self.quota(session, ctx, now=now)
            self._enforce_quota(quota, ctx, now)
            # Timestamps are set here, not by the database: the two messages of one turn
            # must order correctly even when they share a transaction.
            user_message = AIMessage(
                business_id=ctx.business_id,
                conversation_id=conversation.id,
                role=AIMessageRole.USER,
                content=content,
                created_at=datetime.now(UTC),
            )
            async with transaction(session):
                await ai_repo.add_message(session, user_message)
                if conversation.title is None:
                    conversation.title = content[:120]
            history = [*history, user_message]
        else:
            user_message = reuse

        business = await business_repo.get_business(session, ctx.business_id)
        user = await user_repo.get_user_by_id(session, ctx.user_id)
        if business is None or user is None:  # pragma: no cover - the context guarantees both
            raise NotFoundError("Business not found")

        system: list[dict[str, Any]] = [
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
            {
                "type": "text",
                "text": volatile_context(
                    ctx,
                    business_name=business.name,
                    business_type=business.business_type.value,
                    currency=business.currency,
                    user_first_name=user.full_name.split(" ")[0],
                    now=now,
                ),
            },
        ]
        messages = self._history_messages(history)
        tools = tool_definitions()
        started = time.monotonic()
        usage = Usage()
        tool_records: list[dict[str, Any]] = []
        response: ProviderResponse | None = None
        model_used = self._settings.ai_model
        proposal: StoredProposal | None = None

        for round_index in range(self._settings.ai_max_tool_rounds + 1):
            response = await self._provider.complete(
                system=system,
                tools=tools,
                messages=messages,
                max_tokens=self._settings.ai_max_output_tokens,
            )
            usage = usage + response.usage
            model_used = response.model or model_used
            logger.info(
                "ai turn",
                extra={
                    "business_id": str(ctx.business_id),
                    "conversation_id": str(conversation.id),
                    "round": round_index,
                    "stop_reason": response.stop_reason,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "cache_creation_input_tokens": response.usage.cache_creation_input_tokens,
                    "cache_read_input_tokens": response.usage.cache_read_input_tokens,
                    "tool_calls": [c.name for c in response.tool_calls],
                },
            )
            if response.unsupported_blocks:
                logger.error(
                    "ai response with unsupported blocks",
                    extra={"blocks": response.unsupported_blocks},
                )
                raise AIUnavailableError(
                    "The assistant gave an answer we could not use. Please try again.",
                    code="AI_INVALID_RESPONSE",
                )
            if response.stop_reason != "tool_use" or not response.tool_calls:
                break
            proposal_call = next((c for c in response.tool_calls if c.name in PROPOSAL_TOOLS), None)
            if proposal_call is not None:
                # A proposal ends the turn: it is stored for the owner to confirm, never run.
                # The model's own text is the answer shown next to it.
                proposal = self._capture_proposal(proposal_call, tool_records)
                break
            if round_index == self._settings.ai_max_tool_rounds:
                logger.warning(
                    "ai tool round limit reached", extra={"conversation_id": str(conversation.id)}
                )
                raise AIUnavailableError(
                    "The assistant could not finish that question. Please ask something simpler.",
                    code="AI_INCOMPLETE",
                )
            messages.append({"role": "assistant", "content": response.content})
            results = [
                await self._run_tool(session, ctx, call, now, tool_records)
                for call in response.tool_calls
            ]
            messages.append({"role": "user", "content": results})

        if response is None:  # pragma: no cover - the loop always runs at least once
            raise AIUnavailableError("The assistant did not answer. Please try again.")
        if response.stop_reason == "refusal":
            raise AIUnavailableError(
                "The assistant declined to answer that. Please rephrase your question.",
                code="AI_REFUSED",
            )
        if not response.text and proposal is None:
            raise AIUnavailableError(
                "The assistant gave an empty answer. Please try again.", code="AI_INVALID_RESPONSE"
            )

        assistant_message = AIMessage(
            business_id=ctx.business_id,
            conversation_id=conversation.id,
            role=AIMessageRole.ASSISTANT,
            content=response.text or _PROPOSAL_FALLBACK_TEXT[proposal.kind if proposal else None],
            tool_calls=tool_records or None,
            proposal=proposal.model_dump(mode="json") if proposal else None,
            proposal_status=ProposalStatus.PENDING if proposal else None,
            model=model_used[:60],
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_input_tokens,
            stop_reason=response.stop_reason[:30],
            latency_ms=int((time.monotonic() - started) * 1000),
            created_at=datetime.now(UTC),
        )
        async with transaction(session):
            await ai_repo.add_message(session, assistant_message)
            conversation.updated_at = datetime.now(UTC)
        quota = await self.quota(session, ctx, now=now)
        return AskResult(
            conversation=conversation,
            user_message=user_message,
            assistant_message=assistant_message,
            quota=quota,
        )

    def _history_messages(self, history: list[AIMessage]) -> list[dict[str, Any]]:
        window = history[-self._settings.ai_history_messages :]
        messages: list[dict[str, Any]] = []
        for message in window:
            role = "user" if message.role == AIMessageRole.USER else "assistant"
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] = f"{messages[-1]['content']}\n\n{message.content}"
            else:
                messages.append({"role": role, "content": message.content})
        if messages and messages[0]["role"] != "user":
            messages.pop(0)
        return messages

    def _capture_proposal(
        self, call: ToolCall, records: list[dict[str, Any]]
    ) -> StoredProposal | None:
        """Validate a propose_* call's arguments; an invalid one is dropped, not executed."""
        kind = PROPOSAL_TOOLS[call.name]
        try:
            parsed = validate_proposal(kind, call.input)
        except ValidationError as exc:
            logger.warning(
                "ai proposal rejected", extra={"tool": call.name, "errors": len(exc.errors())}
            )
            records.append({"name": call.name, "input": call.input, "ok": False, "duration_ms": 0})
            return None
        records.append({"name": call.name, "input": call.input, "ok": True, "duration_ms": 0})
        return StoredProposal(kind=kind, payload=parsed.model_dump(mode="json"))

    async def _run_tool(
        self,
        session: AsyncSession,
        ctx: BusinessContext,
        call: ToolCall,
        now: datetime,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        started = time.monotonic()
        tool = TOOLS.get(call.name)
        ok = False
        if tool is None:
            output = json.dumps({"error": f"Unknown tool '{call.name[:40]}'"})
        else:
            try:
                args = tool.input_model.model_validate(call.input)
            except ValidationError as exc:
                output = json.dumps(
                    {
                        "error": "Invalid arguments",
                        "details": [
                            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                            for e in exc.errors()
                        ][:5],
                    }
                )
            else:
                # Tools run inside a savepoint set to read-only: any write fails at the database,
                # and rolling the savepoint back reverts the setting for the rest of the request.
                savepoint = await session.begin_nested()
                try:
                    await session.execute(text("SET LOCAL transaction_read_only = on"))
                    result = await tool.run(session, ctx, args, now)
                    output = serialise_result(result)
                    ok = True
                except ToolInputError as exc:
                    output = json.dumps({"error": str(exc)})
                except Exception:
                    logger.exception("ai tool failed", extra={"tool": call.name})
                    output = json.dumps({"error": "That information is not available right now"})
                finally:
                    await savepoint.rollback()
        duration_ms = int((time.monotonic() - started) * 1000)
        records.append(
            {
                "name": call.name[:60],
                "input": call.input,
                "ok": ok,
                "duration_ms": duration_ms,
                "output_summary": output[:OUTPUT_SUMMARY_CHARS],
            }
        )
        return {
            "type": "tool_result",
            "tool_use_id": call.id,
            "content": output,
            "is_error": not ok,
        }
