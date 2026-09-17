"""The model provider boundary (PRD AI-1).

`AIProvider` is the one interface the orchestrator talks to; `AnthropicProvider`
implements it with the official SDK. Tests substitute a scripted provider at this
boundary — production code has no fake path.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from app.ai.errors import AIUnavailableError
from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_creation_input_tokens + other.cache_creation_input_tokens,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
        )


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """One model turn. `content` is the raw block list, replayed verbatim on tool rounds."""

    content: list[dict[str, Any]]
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    usage: Usage
    model: str
    unsupported_blocks: list[str] = field(default_factory=list)


class AIProvider(Protocol):
    async def complete(
        self,
        *,
        system: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse: ...


_ALLOWED_BLOCKS = frozenset({"text", "tool_use", "thinking", "redacted_thinking"})


def parse_message(message: anthropic.types.Message) -> ProviderResponse:
    content: list[dict[str, Any]] = []
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    unsupported: list[str] = []
    for block in message.content:
        block_type = getattr(block, "type", "?")
        if block_type not in _ALLOWED_BLOCKS:
            unsupported.append(block_type)
            continue
        content.append(block.model_dump(exclude_none=True))
        if block_type == "text":
            text_parts.append(getattr(block, "text", ""))
        elif block_type == "tool_use":
            raw = getattr(block, "input", {})
            calls.append(
                ToolCall(
                    id=str(getattr(block, "id", "")),
                    name=str(getattr(block, "name", "")),
                    input=dict(raw) if isinstance(raw, dict) else {},
                )
            )
    usage = message.usage
    return ProviderResponse(
        content=content,
        text="".join(text_parts).strip(),
        tool_calls=calls,
        stop_reason=str(message.stop_reason or "end_turn"),
        usage=Usage(
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_input_tokens=usage.cache_read_input_tokens or 0,
        ),
        model=message.model,
        unsupported_blocks=unsupported,
    )


class AnthropicProvider:
    def __init__(self, settings: Settings) -> None:
        if settings.anthropic_api_key is None:
            msg = "ANTHROPIC_API_KEY is not configured"
            raise ValueError(msg)
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=settings.ai_request_timeout_seconds,
            max_retries=1,
        )
        self._model = settings.ai_model
        self._thinking = settings.ai_thinking

    async def complete(
        self,
        *,
        system: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse:
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "system": system,
            "tools": tools,
            "messages": messages,
        }
        if self._thinking == "adaptive":
            params["thinking"] = {"type": "adaptive"}
        try:
            message = await self._client.messages.create(**params)
        except anthropic.APITimeoutError:
            logger.warning("ai provider timeout", extra={"ai_model": self._model})
            raise AIUnavailableError(
                "The assistant took too long to answer. Please try again.", code="AI_TIMEOUT"
            ) from None
        except anthropic.RateLimitError:
            logger.warning("ai provider rate limited", extra={"ai_model": self._model})
            raise AIUnavailableError(
                "The assistant is busy right now. Please try again in a moment.",
                code="AI_PROVIDER_BUSY",
                headers={"Retry-After": "30"},
            ) from None
        except anthropic.APIConnectionError:
            logger.warning("ai provider unreachable", extra={"ai_model": self._model})
            raise AIUnavailableError(
                "The assistant is unavailable right now. Please try again."
            ) from None
        except anthropic.APIStatusError as exc:
            # Never relay the provider's message: it can name the model, key state or request shape.
            logger.error(
                "ai provider error",
                extra={"ai_model": self._model, "provider_status": exc.status_code},
            )
            raise AIUnavailableError(
                "The assistant is unavailable right now. Please try again."
            ) from None
        return parse_message(message)


def build_provider(settings: Settings) -> AIProvider | None:
    return AnthropicProvider(settings) if settings.anthropic_api_key else None
