"""Outbound SMS for password reset codes (docs/ARCHITECTURE.md §5.1).

One protocol, two implementations. `ConsoleSmsSender` is for development: it logs the
message with the phone masked, so a code can be read from the local log. It is refused in
production by the settings (`check_sms_provider`). `AfricasTalkingSmsSender` posts to the
Africa's Talking messaging API. Phones are never logged in full anywhere.
"""

import logging
from typing import Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

AFRICASTALKING_URL = "https://api.africastalking.com/version1/messaging"
# The sandbox app (username "sandbox") lives on its own host; messages go to the simulator.
AFRICASTALKING_SANDBOX_URL = "https://api.sandbox.africastalking.com/version1/messaging"
SMS_TIMEOUT_SECONDS = 10.0


class SmsDeliveryError(Exception):
    """The provider did not accept the message. Never carries the message text."""


class SmsSender(Protocol):
    async def send(self, phone: str, text: str) -> None: ...


def mask_phone(phone: str) -> str:
    return f"***{phone[-3:]}" if len(phone) >= 3 else "***"


class ConsoleSmsSender:
    """Development only: the message goes to the log instead of a phone."""

    async def send(self, phone: str, text: str) -> None:
        logger.info("sms (console)", extra={"to": mask_phone(phone), "text": text})


class AfricasTalkingSmsSender:
    def __init__(
        self, *, username: str, api_key: str, sender_id: str | None, url: str | None = None
    ) -> None:
        self._username = username
        self._api_key = api_key
        self._sender_id = sender_id
        self._url = url or (
            AFRICASTALKING_SANDBOX_URL if username == "sandbox" else AFRICASTALKING_URL
        )

    async def send(self, phone: str, text: str) -> None:
        data = {"username": self._username, "to": phone, "message": text}
        if self._sender_id:
            data["from"] = self._sender_id
        headers = {"apiKey": self._api_key, "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=SMS_TIMEOUT_SECONDS) as client:
                response = await client.post(self._url, data=data, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("sms delivery failed", extra={"reason": type(exc).__name__})
            raise SmsDeliveryError from exc
        if response.status_code >= 300:
            logger.warning("sms delivery failed", extra={"status": response.status_code})
            raise SmsDeliveryError
        status = _recipient_status(response)
        if status is not None and not status.lower().startswith("success"):
            logger.warning("sms not accepted", extra={"status": status})
            raise SmsDeliveryError


def _recipient_status(response: httpx.Response) -> str | None:
    try:
        body = response.json()
        recipients = body["SMSMessageData"]["Recipients"]
        return str(recipients[0]["status"]) if recipients else "no recipients"
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def build_sms_sender(settings: Settings) -> SmsSender | None:
    """None → password reset answers 503 PASSWORD_RESET_NOT_CONFIGURED."""
    if settings.sms_provider == "console":
        return ConsoleSmsSender()
    if settings.sms_provider == "africastalking":
        if not settings.africastalking_username or settings.africastalking_api_key is None:
            return None  # pragma: no cover — the settings validator refuses this combination
        return AfricasTalkingSmsSender(
            username=settings.africastalking_username,
            api_key=settings.africastalking_api_key.get_secret_value(),
            sender_id=settings.africastalking_sender_id,
        )
    return None


__all__ = [
    "AFRICASTALKING_SANDBOX_URL",
    "AFRICASTALKING_URL",
    "AfricasTalkingSmsSender",
    "ConsoleSmsSender",
    "SmsDeliveryError",
    "SmsSender",
    "build_sms_sender",
    "mask_phone",
]
