"""POST /api/v1/auth/login (PRD FR-B2, ARCHITECTURE §5.2)."""

import uuid
from http import HTTPStatus

import pytest
from app.core.passwords import hash_password, needs_rehash
from app.models import BusinessMembership, User
from argon2 import PasswordHasher
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import (
    LOGIN_URL,
    OTHER_PASSWORD,
    PASSWORD,
    add_staff,
    client_from_ip,
    error_code,
    login,
    refresh_cookie,
    register,
    set_business_active,
)
from tests.db.conftest import ApiFactory

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def test_login_with_phone_returns_a_session(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api, phone="+254700222111")).json()
    api.cookies.clear()
    response = await login(api, "0700 222 111")  # local format normalises to the same number
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert body["user"]["id"] == registered["user"]["id"]
    assert body["business"]["id"] == registered["business"]["id"]
    assert body["role"] == "OWNER"
    assert body["access_token"] != registered["access_token"]
    assert refresh_cookie(api) is not None
    user = await db_session.get(User, uuid.UUID(body["user"]["id"]))
    assert user is not None and user.last_login_at is not None


async def test_login_with_email_is_case_insensitive(api: AsyncClient) -> None:
    await register(api, email="owner@example.com")
    response = await login(api, "Owner@Example.COM")
    assert response.status_code == HTTPStatus.OK


@pytest.mark.parametrize(
    "identifier", ["+254799999999", "nobody@example.com", "not-a-phone", "%", ""]
)
async def test_unknown_identifier_and_wrong_password_look_the_same(
    api: AsyncClient, identifier: str
) -> None:
    await register(api, phone="+254700222333")
    api.cookies.clear()
    unknown = await api.post(
        LOGIN_URL, json={"identifier": identifier or "x", "password": PASSWORD}
    )
    wrong = await login(api, "+254700222333", "definitely not it")
    assert unknown.status_code == wrong.status_code == HTTPStatus.UNAUTHORIZED
    assert error_code(unknown) == error_code(wrong) == "INVALID_CREDENTIALS"
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]
    assert unknown.headers["www-authenticate"] == "Bearer"
    assert refresh_cookie(api) is None


async def test_deactivated_user_cannot_log_in(api: AsyncClient, db_session: AsyncSession) -> None:
    body = (await register(api, phone="+254700222444")).json()
    user = await db_session.get(User, uuid.UUID(body["user"]["id"]))
    assert user is not None
    user.is_active = False
    await db_session.flush()
    response = await login(api, "+254700222444")
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert error_code(response) == "INVALID_CREDENTIALS"  # indistinguishable from a bad password


async def test_inactive_business_blocks_login(api: AsyncClient, db_session: AsyncSession) -> None:
    body = (await register(api, phone="+254700222555")).json()
    api.cookies.clear()
    await set_business_active(db_session, uuid.UUID(body["business"]["id"]), False)
    response = await login(api, "+254700222555")
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert error_code(response) == "BUSINESS_INACTIVE"
    assert refresh_cookie(api) is None


async def test_inactive_membership_blocks_login(api: AsyncClient, db_session: AsyncSession) -> None:
    body = (await register(api)).json()
    staff = await add_staff(db_session, uuid.UUID(body["business"]["id"]), phone="+254700222666")
    row = (
        await db_session.scalars(
            select(BusinessMembership).where(BusinessMembership.user_id == staff.id)
        )
    ).one()
    row.is_active = False
    await db_session.flush()
    response = await login(api, "+254700222666")
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert error_code(response) == "MEMBERSHIP_INACTIVE"


async def test_staff_login_reports_the_staff_role(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    body = (await register(api)).json()
    await add_staff(db_session, uuid.UUID(body["business"]["id"]), phone="+254700222777")
    response = await login(api, "+254700222777")
    assert response.status_code == HTTPStatus.OK
    assert response.json()["role"] == "STAFF"
    assert response.json()["business"]["id"] == body["business"]["id"]


async def test_login_rehashes_passwords_made_with_old_parameters(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    body = (await register(api, phone="+254700222888")).json()
    user = await db_session.get(User, uuid.UUID(body["user"]["id"]))
    assert user is not None
    user.password_hash = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash(
        PASSWORD
    )
    await db_session.flush()
    assert needs_rehash(user.password_hash)
    assert (await login(api, "+254700222888")).status_code == HTTPStatus.OK
    await db_session.refresh(user)
    assert not needs_rehash(user.password_hash)
    assert user.password_hash != hash_password(PASSWORD)  # new salt, current parameters


async def test_login_is_rate_limited_per_identifier_without_revealing_existence(
    api_factory: ApiFactory,
) -> None:
    api = await api_factory(rate_limit_login_per_minute=3)
    await register(api, phone="+254700333111")
    # Every attempt from a different address, so only the per-identifier counter can trip.
    real, ghost = [], []
    for i in range(4):
        async with client_from_ip(api, f"10.0.0.{i}") as attacker:
            real.append(await login(attacker, "+254700333111", "wrong"))
        async with client_from_ip(api, f"10.0.1.{i}") as attacker:
            ghost.append(await login(attacker, "+254700333222", "wrong"))
    # Both sequences: three 401s then a 429 with the same body shape.
    assert [r.status_code for r in real[:3]] == [HTTPStatus.UNAUTHORIZED] * 3
    assert [r.status_code for r in ghost[:3]] == [HTTPStatus.UNAUTHORIZED] * 3
    assert real[3].status_code == ghost[3].status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert error_code(real[3]) == error_code(ghost[3]) == "RATE_LIMITED"
    assert real[3].json()["error"]["message"] == ghost[3].json()["error"]["message"]


async def test_login_is_rate_limited_per_ip(api_factory: ApiFactory) -> None:
    api = await api_factory(rate_limit_login_per_minute=2)
    await register(api, phone="+254700333333")
    assert (await login(api, "+254700333333")).status_code == HTTPStatus.OK
    assert (await login(api, "+254700333444")).status_code == HTTPStatus.UNAUTHORIZED
    blocked = await login(api, "+254700333555")
    assert blocked.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert "retry-after" in blocked.headers


async def test_login_rejects_unknown_fields(api: AsyncClient) -> None:
    response = await api.post(
        LOGIN_URL,
        json={
            "identifier": "+254700333666",
            "password": PASSWORD,
            "business_id": "x",
            "role": "OWNER",
        },
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_login_response_never_contains_secrets(api: AsyncClient) -> None:
    await register(api, phone="+254700333777")
    response = await login(api, "+254700333777")
    assert PASSWORD not in response.text
    assert OTHER_PASSWORD not in response.text
    assert "password_hash" not in response.text
    assert "$argon2" not in response.text
    cookie = refresh_cookie(api)
    assert cookie is not None and cookie not in response.text
