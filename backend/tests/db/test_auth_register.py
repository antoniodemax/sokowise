"""POST /api/v1/auth/register (PRD FR-A1, FR-A2, FR-B1)."""

import uuid
from http import HTTPStatus

import pytest
from app.api.v1.auth import REFRESH_COOKIE_NAME
from app.models import Business, BusinessMembership, RefreshToken, User
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import (
    ME_URL,
    PASSWORD,
    REGISTER_URL,
    bearer,
    error_code,
    refresh_cookie,
    register,
    register_payload,
)

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def test_register_creates_user_business_and_owner_membership(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    payload = register_payload(phone="0712 345 678", email="Amina@Example.com")
    response = await api.post(REGISTER_URL, json=payload)
    assert response.status_code == HTTPStatus.CREATED, response.text
    body = response.json()

    assert set(body) == {"access_token", "token_type", "expires_in", "user", "business", "role"}
    assert body["role"] == "OWNER"
    assert body["token_type"] == "bearer"  # noqa: S105
    assert body["expires_in"] == 15 * 60
    assert body["user"]["phone"] == "+254712345678"  # normalised
    assert body["user"]["email"] == "amina@example.com"  # lower-cased
    assert body["user"]["must_change_password"] is False
    assert "password_hash" not in response.text and PASSWORD not in response.text
    assert body["business"]["name"] == "Amina Duka"
    assert body["business"]["currency"] == "KES"
    assert body["business"]["timezone"] == "Africa/Nairobi"

    user_id = uuid.UUID(body["user"]["id"])
    business_id = uuid.UUID(body["business"]["id"])
    membership = (
        await db_session.scalars(
            select(BusinessMembership).where(BusinessMembership.user_id == user_id)
        )
    ).one()
    assert (membership.business_id, membership.role.value, membership.is_active) == (
        business_id,
        "OWNER",
        True,
    )
    user = await db_session.get(User, user_id)
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash

    # The session is usable straight away.
    me = await api.get(ME_URL, headers=bearer(body["access_token"]))
    assert me.status_code == HTTPStatus.OK
    assert me.json()["business"]["id"] == str(business_id)


async def test_register_sets_the_refresh_cookie_and_stores_only_its_hash(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    response = await register(api)
    assert response.status_code == HTTPStatus.CREATED
    raw = refresh_cookie(api)
    assert raw is not None and len(raw) >= 43
    assert raw not in response.text  # never in the body
    rows = (await db_session.scalars(select(RefreshToken))).all()
    hashes = {row.token_hash for row in rows}
    assert raw not in hashes
    assert len(hashes) == 1 and all(len(h) == 64 for h in hashes)
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{REFRESH_COOKIE_NAME}=")


async def test_duplicate_phone_is_a_conflict_that_names_no_owner(api: AsyncClient) -> None:
    phone = "+254700111222"
    first = await register(api, phone=phone)
    assert first.status_code == HTTPStatus.CREATED
    second = await register(api, phone=phone, business_name="Another Duka")
    assert second.status_code == HTTPStatus.CONFLICT
    assert error_code(second) == "ACCOUNT_EXISTS"
    assert "Another" not in second.text and "Amina" not in second.text


async def test_duplicate_email_is_a_conflict(api: AsyncClient) -> None:
    email = "same@example.com"
    assert (await register(api, email=email)).status_code == HTTPStatus.CREATED
    second = await register(api, email=email.upper())
    assert second.status_code == HTTPStatus.CONFLICT
    assert error_code(second) == "ACCOUNT_EXISTS"


async def test_failed_registration_leaves_no_rows_behind(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    phone = "+254700111333"
    assert (await register(api, phone=phone)).status_code == HTTPStatus.CREATED
    before = await db_session.scalar(select(func.count()).select_from(Business))
    duplicate = await register(api, phone=phone, business_name="Ghost Duka")
    assert duplicate.status_code == HTTPStatus.CONFLICT
    after = await db_session.scalar(select(func.count()).select_from(Business))
    assert after == before
    ghosts = (await db_session.scalars(select(Business).where(Business.name == "Ghost Duka"))).all()
    assert ghosts == []


async def test_business_names_need_not_be_unique(api: AsyncClient) -> None:
    """DATA_MAPPING §3.1 has no uniqueness on businesses.name: two shops may share one."""
    first = await register(api, business_name="Mama Mboga")
    second = await register(api, business_name="Mama Mboga")
    assert first.status_code == HTTPStatus.CREATED
    assert second.status_code == HTTPStatus.CREATED
    assert first.json()["business"]["id"] != second.json()["business"]["id"]


async def test_client_cannot_choose_a_role(api: AsyncClient, db_session: AsyncSession) -> None:
    response = await api.post(REGISTER_URL, json=register_payload(role="STAFF"))
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert error_code(response) == "VALIDATION_ERROR"
    assert any(d["loc"][-1] == "role" for d in response.json()["error"]["details"])
    # Nothing was created.
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


async def test_email_is_optional(api: AsyncClient) -> None:
    payload = register_payload()
    del payload["email"]
    response = await api.post(REGISTER_URL, json=payload)
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()["user"]["email"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("password", "short"),
        ("password", "password123"),
        ("password", "x" * 129),
        ("phone", "12345"),
        ("email", "not-an-email"),
        ("full_name", ""),
        ("business_name", ""),
        ("business_type", "BANK"),
        ("timezone", "Mars/Olympus"),
    ],
)
async def test_invalid_input_is_a_validation_error(
    api: AsyncClient, field: str, value: str
) -> None:
    response = await api.post(REGISTER_URL, json=register_payload(**{field: value}))
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    assert error_code(response) == "VALIDATION_ERROR"
    assert any(d["loc"][-1] == field for d in response.json()["error"]["details"])
    assert PASSWORD not in response.text


async def test_registration_is_rate_limited_per_ip(api_factory: object) -> None:
    from tests.db.conftest import ApiFactory

    factory: ApiFactory = api_factory  # type: ignore[assignment]
    api = await factory(rate_limit_register_per_minute=2)
    assert (await register(api)).status_code == HTTPStatus.CREATED
    assert (await register(api)).status_code == HTTPStatus.CREATED
    blocked = await register(api)
    assert blocked.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert error_code(blocked) == "RATE_LIMITED"
    assert int(blocked.headers["retry-after"]) >= 1
