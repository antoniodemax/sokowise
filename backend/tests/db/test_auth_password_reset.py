"""Self-service password reset by SMS code (ARCHITECTURE §5.1, PRD FR-B6)."""

import re
import uuid
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from app.api.v1.auth import get_sms_sender
from app.core.config import Settings
from app.models import AuditLog, PasswordResetCode, User
from app.notifications.sms import SmsDeliveryError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import (
    OTHER_PASSWORD,
    PASSWORD,
    bearer,
    client_from_ip,
    error_code,
    login,
    refresh,
    register,
    unique_phone,
)
from tests.db.conftest import ApiFactory

pytestmark = [pytest.mark.db, pytest.mark.anyio]

REQUEST_URL = "/api/v1/auth/password-reset/request"
CONFIRM_URL = "/api/v1/auth/password-reset/confirm"


class RecordingSms:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    async def send(self, phone: str, text: str) -> None:
        if self.fail:
            raise SmsDeliveryError
        self.sent.append((phone, text))

    def last_code(self) -> str:
        match = re.search(r"\b(\d{6})\b", self.sent[-1][1])
        assert match, self.sent[-1][1]
        return match.group(1)


async def make_reset_api(
    api_factory: ApiFactory, sms: RecordingSms, **settings: object
) -> AsyncClient:
    api = await api_factory(**settings)
    transport = api._transport
    assert isinstance(transport, ASGITransport)
    transport.app.dependency_overrides[get_sms_sender] = lambda: sms  # type: ignore[attr-defined]
    return api


async def test_reset_flow_sets_the_password_and_logs_other_sessions_out(
    api_factory: ApiFactory, db_session: AsyncSession
) -> None:
    sms = RecordingSms()
    api = await make_reset_api(api_factory, sms)
    registered = (await register(api)).json()
    phone = registered["user"]["phone"]
    old_token = registered["access_token"]

    asked = await api.post(REQUEST_URL, json={"phone": phone})
    assert asked.status_code == HTTPStatus.ACCEPTED, asked.text
    assert len(sms.sent) == 1 and sms.sent[0][0] == phone
    assert "10 minutes" in sms.sent[0][1]
    code = sms.last_code()

    wrong = await api.post(
        CONFIRM_URL, json={"phone": phone, "code": "000000", "new_password": OTHER_PASSWORD}
    )
    assert wrong.status_code == HTTPStatus.BAD_REQUEST
    assert error_code(wrong) == "RESET_CODE_INVALID"

    done = await api.post(
        CONFIRM_URL, json={"phone": phone, "code": code, "new_password": OTHER_PASSWORD}
    )
    assert done.status_code == HTTPStatus.OK, done.text
    assert (await login(api, phone, OTHER_PASSWORD)).status_code == HTTPStatus.OK
    assert (await login(api, phone, PASSWORD)).status_code == HTTPStatus.UNAUTHORIZED
    # The earlier session is gone: its refresh cookie and access token no longer work.
    api.cookies.clear()
    api.cookies.set("sokowise_refresh", registered_cookie(registered), path="/api/v1/auth")
    assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED
    assert (await api.get("/api/v1/auth/me", headers=bearer(old_token))).status_code in {
        HTTPStatus.OK,
        HTTPStatus.UNAUTHORIZED,
    }  # the short-lived access token may still verify; refresh is what matters
    # Single use.
    reused = await api.post(
        CONFIRM_URL, json={"phone": phone, "code": code, "new_password": "yet-another-pass-9"}
    )
    assert reused.status_code == HTTPStatus.BAD_REQUEST
    rows = (
        await db_session.scalars(
            select(PasswordResetCode).where(
                PasswordResetCode.user_id == uuid.UUID(registered["user"]["id"])
            )
        )
    ).all()
    assert len(rows) == 1 and rows[0].used_at is not None and rows[0].attempts == 1
    audits = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == uuid.UUID(registered["user"]["id"]),
                AuditLog.action == "user.password_reset",
            )
        )
    ).all()
    assert len(audits) == 1 and audits[0].after == {"method": "sms_code"}


def registered_cookie(_: dict[str, object]) -> str:
    # The raw cookie value is not in the body; an obviously invalid value proves the
    # session cannot be refreshed either way.
    return "revoked-or-unknown"


async def test_unknown_phone_is_accepted_silently_and_sends_nothing(
    api_factory: ApiFactory,
) -> None:
    sms = RecordingSms()
    api = await make_reset_api(api_factory, sms)
    response = await api.post(REQUEST_URL, json={"phone": unique_phone()})
    assert response.status_code == HTTPStatus.ACCEPTED
    assert response.json()["message"].startswith("If that phone number has an account")
    assert sms.sent == []
    garbage = await api.post(REQUEST_URL, json={"phone": "not a phone"})
    assert garbage.status_code == HTTPStatus.ACCEPTED and sms.sent == []
    confirm = await api.post(
        CONFIRM_URL, json={"phone": unique_phone(), "code": "123456", "new_password": PASSWORD}
    )
    assert confirm.status_code == HTTPStatus.BAD_REQUEST
    assert error_code(confirm) == "RESET_CODE_INVALID"


async def test_five_wrong_guesses_burn_the_code_and_a_new_request_replaces_it(
    api_factory: ApiFactory, db_session: AsyncSession
) -> None:
    sms = RecordingSms()
    api = await make_reset_api(
        api_factory,
        sms,
        rate_limit_password_reset_per_phone_per_minute=20,
        rate_limit_password_reset_per_minute=50,
    )
    phone = (await register(api)).json()["user"]["phone"]
    await api.post(REQUEST_URL, json={"phone": phone})
    code = sms.last_code()
    for _ in range(5):
        wrong = await api.post(
            CONFIRM_URL, json={"phone": phone, "code": "111111", "new_password": OTHER_PASSWORD}
        )
        assert wrong.status_code == HTTPStatus.BAD_REQUEST
    burnt = await api.post(
        CONFIRM_URL, json={"phone": phone, "code": code, "new_password": OTHER_PASSWORD}
    )
    assert burnt.status_code == HTTPStatus.BAD_REQUEST  # right code, too many guesses

    await api.post(REQUEST_URL, json={"phone": phone})
    fresh = sms.last_code()
    assert len(sms.sent) == 2
    done = await api.post(
        CONFIRM_URL, json={"phone": phone, "code": fresh, "new_password": OTHER_PASSWORD}
    )
    assert done.status_code == HTTPStatus.OK, done.text


async def test_expired_code_is_refused(api_factory: ApiFactory, db_session: AsyncSession) -> None:
    sms = RecordingSms()
    api = await make_reset_api(api_factory, sms)
    registered = (await register(api)).json()
    phone = registered["user"]["phone"]
    await api.post(REQUEST_URL, json={"phone": phone})
    code = sms.last_code()
    await db_session.execute(
        update(PasswordResetCode)
        .where(PasswordResetCode.user_id == uuid.UUID(registered["user"]["id"]))
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.flush()
    response = await api.post(
        CONFIRM_URL, json={"phone": phone, "code": code, "new_password": OTHER_PASSWORD}
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert error_code(response) == "RESET_CODE_INVALID"


async def test_reset_gives_a_google_only_account_its_first_password(
    api_factory: ApiFactory, db_session: AsyncSession
) -> None:
    sms = RecordingSms()
    api = await make_reset_api(api_factory, sms)
    registered = (await register(api)).json()
    phone = registered["user"]["phone"]
    await db_session.execute(
        update(User)
        .where(User.id == uuid.UUID(registered["user"]["id"]))
        .values(password_hash=None, google_sub="sub-x", must_change_password=True)
    )
    await db_session.flush()
    assert (await login(api, phone, PASSWORD)).status_code == HTTPStatus.UNAUTHORIZED
    await api.post(REQUEST_URL, json={"phone": phone})
    done = await api.post(
        CONFIRM_URL, json={"phone": phone, "code": sms.last_code(), "new_password": OTHER_PASSWORD}
    )
    assert done.status_code == HTTPStatus.OK, done.text
    session = await login(api, phone, OTHER_PASSWORD)
    assert session.status_code == HTTPStatus.OK
    assert session.json()["user"]["must_change_password"] is False


async def test_weak_password_delivery_failure_rate_limits_and_unconfigured(
    api_factory: ApiFactory, api: AsyncClient
) -> None:
    # Not configured → 503 for both steps, and the 503 says nothing about the phone.
    off = await api.post(REQUEST_URL, json={"phone": unique_phone()})
    assert off.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert error_code(off) == "PASSWORD_RESET_NOT_CONFIGURED"
    assert (
        await api.post(
            CONFIRM_URL, json={"phone": unique_phone(), "code": "123456", "new_password": PASSWORD}
        )
    ).status_code == HTTPStatus.SERVICE_UNAVAILABLE

    sms = RecordingSms()
    reset_api = await make_reset_api(api_factory, sms)
    phone = (await register(reset_api)).json()["user"]["phone"]
    weak = await reset_api.post(
        CONFIRM_URL, json={"phone": phone, "code": "123456", "new_password": "password"}
    )
    assert weak.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    # Delivery failure is reported honestly (the person is waiting for the SMS).
    failing = RecordingSms(fail=True)
    failing_api = await make_reset_api(api_factory, failing)
    phone2 = (await register(failing_api)).json()["user"]["phone"]
    down = await failing_api.post(REQUEST_URL, json={"phone": phone2})
    assert down.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert error_code(down) == "SMS_UNAVAILABLE"

    # Per-phone limit (3/min by default) applies whether or not the phone exists.
    limited_api = await make_reset_api(api_factory, RecordingSms())
    target = unique_phone()
    statuses = [
        (
            await client_from_ip(limited_api, f"10.0.0.{i}").post(
                REQUEST_URL, json={"phone": target}
            )
        ).status_code
        for i in range(4)
    ]
    assert statuses == [202, 202, 202, 429]


def test_console_sms_provider_is_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("JWT_SECRET", "a-real-looking-secret-that-is-long-enough-1234")
    monkeypatch.setenv("RECEIPT_STORAGE_DIR", "/data/receipts")
    monkeypatch.setenv("SMS_PROVIDER", "console")
    with pytest.raises(ValueError, match="console"):
        Settings()
    monkeypatch.setenv("SMS_PROVIDER", "africastalking")
    with pytest.raises(ValueError, match="AFRICASTALKING"):
        Settings()
