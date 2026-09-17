"""The provider boundary: SDK errors become safe envelopes; responses are parsed strictly."""

from typing import Any

import anthropic
import httpx
import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from app.ai.errors import AIUnavailableError
from app.ai.provider import AnthropicProvider, parse_message
from app.core.config import Settings

pytestmark = pytest.mark.anyio


def _message(**overrides: Any) -> Message:
    base: dict[str, Any] = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-test",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "content": [TextBlock(type="text", text="Revenue was KSh 1,500.")],
        "usage": Usage(
            input_tokens=100,
            output_tokens=20,
            cache_creation_input_tokens=50,
            cache_read_input_tokens=0,
        ),
    }
    base.update(overrides)
    return Message(**base)


def test_parse_message_extracts_text_tool_calls_and_usage() -> None:
    parsed = parse_message(
        _message(
            stop_reason="tool_use",
            content=[
                TextBlock(type="text", text="Let me check."),
                ToolUseBlock(
                    type="tool_use",
                    id="tu_1",
                    name="get_debtors",
                    input={"sort": "balance", "limit": 5},
                ),
            ],
        )
    )
    assert parsed.text == "Let me check."
    assert [c.name for c in parsed.tool_calls] == ["get_debtors"]
    assert parsed.tool_calls[0].input == {"sort": "balance", "limit": 5}
    assert parsed.stop_reason == "tool_use"
    assert parsed.usage.cache_creation_input_tokens == 50
    assert [b["type"] for b in parsed.content] == ["text", "tool_use"]


def test_parse_message_flags_unsupported_blocks() -> None:
    parsed = parse_message(
        _message(
            content=[{"type": "server_tool_use", "id": "x", "name": "web_search", "input": {}}]
        )
    )  # type: ignore[list-item]
    assert parsed.unsupported_blocks == ["server_tool_use"]
    assert parsed.text == ""


def _provider(monkeypatch: pytest.MonkeyPatch, error: Exception) -> AnthropicProvider:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    provider = AnthropicProvider(Settings())

    async def boom(**_: Any) -> Message:
        raise error

    monkeypatch.setattr(provider._client.messages, "create", boom)
    return provider


async def _complete(provider: AnthropicProvider) -> None:
    await provider.complete(
        system=[], tools=[], messages=[{"role": "user", "content": "hi"}], max_tokens=100
    )


async def test_timeout_rate_limit_connection_and_status_errors_become_safe_503s(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    cases = [
        (anthropic.APITimeoutError(request), "AI_TIMEOUT"),
        (
            anthropic.RateLimitError(
                "slow down", response=httpx.Response(429, request=request), body=None
            ),
            "AI_PROVIDER_BUSY",
        ),
        (anthropic.APIConnectionError(request=request), "AI_UNAVAILABLE"),
        (
            anthropic.AuthenticationError(
                "bad key sk-ant-secret", response=httpx.Response(401, request=request), body=None
            ),
            "AI_UNAVAILABLE",
        ),
        (
            anthropic.InternalServerError(
                "boom", response=httpx.Response(500, request=request), body=None
            ),
            "AI_UNAVAILABLE",
        ),
    ]
    for error, code in cases:
        with pytest.raises(AIUnavailableError) as exc_info:
            await _complete(_provider(monkeypatch, error))
        assert exc_info.value.code == code
        assert exc_info.value.status_code == 503
        assert (
            "sk-ant" not in exc_info.value.message
            and "claude" not in exc_info.value.message.lower()
        )


def test_provider_requires_a_key_and_never_exposes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="not configured"):
        AnthropicProvider(Settings())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret")
    assert "sk-ant-test-secret" not in repr(Settings().anthropic_api_key)
