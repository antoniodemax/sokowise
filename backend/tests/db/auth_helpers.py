"""Shared helpers for the authentication API tests."""

import uuid
from typing import Any

from app.api.deps import CSRF_HEADER, CSRF_HEADER_VALUE
from app.api.v1.auth import REFRESH_COOKIE_NAME, REFRESH_COOKIE_PATH
from app.core.passwords import hash_password
from app.models import Business, BusinessMembership, User
from app.models.enums import MembershipRole
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
LOGOUT_URL = "/api/v1/auth/logout"
LOGOUT_ALL_URL = "/api/v1/auth/logout-all"
CHANGE_PASSWORD_URL = "/api/v1/auth/change-password"  # noqa: S105 — a URL, not a password
ME_URL = "/api/v1/auth/me"

CSRF_HEADERS = {CSRF_HEADER: CSRF_HEADER_VALUE}
PASSWORD = "correct horse battery staple"  # noqa: S105 — test fixture value
OTHER_PASSWORD = "another perfectly fine passphrase"  # noqa: S105


def unique_phone() -> str:
    return "+2547" + str(uuid.uuid4().int)[:8]


def register_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "full_name": "Amina Wanjiru",
        "phone": unique_phone(),
        "email": f"{uuid.uuid4().hex[:10]}@example.com",
        "password": PASSWORD,
        "business_name": "Amina Duka",
        "business_type": "GENERAL_SHOP",
    }
    payload.update(overrides)
    return payload


async def register(api: AsyncClient, **overrides: Any) -> Response:
    return await api.post(REGISTER_URL, json=register_payload(**overrides))


async def login(api: AsyncClient, identifier: str, password: str = PASSWORD) -> Response:
    return await api.post(LOGIN_URL, json={"identifier": identifier, "password": password})


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def refresh_cookie(api: AsyncClient) -> str | None:
    return api.cookies.get(REFRESH_COOKIE_NAME)


def set_refresh_cookie(api: AsyncClient, value: str) -> None:
    """Replace the refresh cookie in the jar (as an attacker or a stale client would)."""
    api.cookies.clear()
    api.cookies.set(REFRESH_COOKIE_NAME, value, domain=api.base_url.host, path=REFRESH_COOKIE_PATH)


async def refresh(api: AsyncClient) -> Response:
    return await api.post(REFRESH_URL, headers=CSRF_HEADERS)


async def add_staff(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    phone: str | None = None,
    password: str = PASSWORD,
    must_change_password: bool = False,
    role: MembershipRole = MembershipRole.STAFF,
) -> User:
    """Create a user directly (the OWNER-creates-STAFF flow is Phase 4)."""
    user = User(
        phone=phone or unique_phone(),
        full_name="Staff Member",
        password_hash=hash_password(password),
        must_change_password=must_change_password,
    )
    session.add(user)
    await session.flush()
    session.add(BusinessMembership(business_id=business_id, user_id=user.id, role=role))
    await session.flush()
    return user


async def set_business_active(session: AsyncSession, business_id: uuid.UUID, active: bool) -> None:
    business = await session.get(Business, business_id)
    assert business is not None
    business.is_active = active
    await session.flush()


def error_code(response: Response) -> str:
    code: str = response.json()["error"]["code"]
    return code


def client_from_ip(api: AsyncClient, ip: str) -> AsyncClient:
    """A second client against the same app (same rate limiter) with another source address."""
    transport = api._transport
    assert isinstance(transport, ASGITransport)
    return AsyncClient(
        transport=ASGITransport(app=transport.app, client=(ip, 40000)),
        base_url=str(api.base_url),
    )
