"""Test doubles and helpers for the copilot (the provider boundary is the seam)."""

import copy
import json
from collections.abc import Callable, Sequence
from typing import Any

from app.ai.provider import ProviderResponse, ToolCall, Usage
from app.api.v1.ai import get_ai_provider
from httpx import ASGITransport, AsyncClient

from tests.db.conftest import ApiFactory

AI_URL = "/api/v1/ai"
Step = ProviderResponse | Exception | Callable[[list[dict[str, Any]]], ProviderResponse]


def text_response(text: str, *, stop_reason: str = "end_turn", **usage: int) -> ProviderResponse:
    return ProviderResponse(
        content=[{"type": "text", "text": text}],
        text=text,
        tool_calls=[],
        stop_reason=stop_reason,
        usage=Usage(**usage) if usage else Usage(input_tokens=100, output_tokens=20),
        model="claude-test",
    )


def tool_response(name: str, input: dict[str, Any], *, call_id: str = "tu_1") -> ProviderResponse:
    return ProviderResponse(
        content=[{"type": "tool_use", "id": call_id, "name": name, "input": input}],
        text="",
        tool_calls=[ToolCall(id=call_id, name=name, input=input)],
        stop_reason="tool_use",
        usage=Usage(input_tokens=120, output_tokens=30, cache_read_input_tokens=90),
        model="claude-test",
    )


class FakeProvider:
    """Plays a script of responses and records every request it received."""

    def __init__(self, script: Sequence[Step]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        system: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> ProviderResponse:
        # Deep-copied: the orchestrator appends to `messages` in place on tool rounds.
        self.requests.append(
            copy.deepcopy(
                {"system": system, "tools": tools, "messages": messages, "max_tokens": max_tokens}
            )
        )
        if not self.script:
            raise AssertionError("the fake provider ran out of scripted responses")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            return step(messages)
        return step

    def tool_results(self, request_index: int = -1) -> list[dict[str, Any]]:
        """The tool_result blocks the backend sent back in a given request."""
        content = self.requests[request_index]["messages"][-1]["content"]
        return [
            block
            for block in content
            if isinstance(block, dict) and block.get("type") == "tool_result"
        ]

    def last_tool_output(self) -> dict[str, Any]:
        result = self.tool_results()[0]
        data: dict[str, Any] = json.loads(result["content"])
        return data


async def make_ai_api(
    api_factory: ApiFactory, provider: FakeProvider | None, **settings: Any
) -> AsyncClient:
    api = await api_factory(**settings)
    transport = api._transport
    assert isinstance(transport, ASGITransport)
    if provider is not None:
        transport.app.dependency_overrides[get_ai_provider] = lambda: provider  # type: ignore[attr-defined]
    return api


async def new_conversation(api: AsyncClient, headers: dict[str, str]) -> str:
    response = await api.post(f"{AI_URL}/conversations", headers=headers, json={})
    assert response.status_code == 201, response.text
    conversation_id: str = response.json()["id"]
    return conversation_id


async def ask(api: AsyncClient, headers: dict[str, str], conversation_id: str, content: str) -> Any:
    return await api.post(
        f"{AI_URL}/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": content},
    )
