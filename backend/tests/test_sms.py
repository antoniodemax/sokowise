"""The Africa's Talking client against a stub transport; the console sender masks phones."""

import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from app.notifications.sms import (
    AfricasTalkingSmsSender,
    ConsoleSmsSender,
    SmsDeliveryError,
    mask_phone,
)

pytestmark = pytest.mark.anyio


def _sender(handler: httpx.MockTransport) -> AfricasTalkingSmsSender:
    sender = AfricasTalkingSmsSender(username="sandbox", api_key="key", sender_id="SOKOWISE")
    # Route the client through the stub transport.
    original = httpx.AsyncClient

    class Patched(original):  # type: ignore[misc,valid-type]
        def __init__(self, **kwargs: Any) -> None:
            kwargs["transport"] = handler
            super().__init__(**kwargs)

    httpx.AsyncClient = Patched  # type: ignore[misc]
    return sender


@pytest.fixture(autouse=True)
def _restore_client() -> Iterator[None]:
    original = httpx.AsyncClient
    yield
    httpx.AsyncClient = original  # type: ignore[misc]


async def test_accepted_message_posts_the_expected_form() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["apikey"] = request.headers.get("apiKey")
        seen["body"] = request.content.decode()
        return httpx.Response(201, json={"SMSMessageData": {"Recipients": [{"status": "Success"}]}})

    await _sender(httpx.MockTransport(handler)).send(
        "+254712345678", "SokoWise: your code is 123456."
    )
    assert seen["url"] == "https://api.africastalking.com/version1/messaging"
    assert seen["apikey"] == "key"
    assert "username=sandbox" in str(seen["body"]) and "from=SOKOWISE" in str(seen["body"])
    assert "to=%2B254712345678" in str(seen["body"])


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, text="denied"),
        httpx.Response(
            201, json={"SMSMessageData": {"Recipients": [{"status": "InvalidPhoneNumber"}]}}
        ),
        httpx.Response(201, json={"SMSMessageData": {"Recipients": []}}),
    ],
)
async def test_rejections_raise_without_the_message_text(response: httpx.Response) -> None:
    sender = _sender(httpx.MockTransport(lambda _request: response))
    with pytest.raises(SmsDeliveryError) as exc_info:
        await sender.send("+254712345678", "secret code 123456")
    assert "123456" not in str(exc_info.value)


async def test_console_sender_masks_the_phone(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="app.notifications.sms"):
        await ConsoleSmsSender().send("+254712345678", "hello")
    record = caplog.records[-1]
    assert getattr(record, "to", None) == "***678" and "+254712345678" not in caplog.text
    assert mask_phone("12") == "***"
