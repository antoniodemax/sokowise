"""POST /api/v1/auth/refresh: rotation, reuse detection, family revocation (PRD FR-B3)."""

import uuid
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from app.api.v1.auth import REFRESH_COOKIE_NAME
from app.core.tokens import hash_refresh_token
from app.models import RefreshToken, User
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import (
    CSRF_HEADERS,
    ME_URL,
    REFRESH_URL,
    bearer,
    error_code,
    refresh,
    refresh_cookie,
    register,
    set_business_active,
    set_refresh_cookie,
)
from tests.db.conftest import ApiFactory

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def _rows(session: AsyncSession, user_id: uuid.UUID) -> list[RefreshToken]:
    # populate_existing: the app shares this session, and its bulk revocations do not
    # update objects already in the identity map.
    result = await session.scalars(
        select(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    return list(result)


async def test_refresh_rotates_the_token_within_one_family(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api)).json()
    user_id = uuid.UUID(registered["user"]["id"])
    first = refresh_cookie(api)
    assert first is not None

    response = await refresh(api)
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert body["user"]["id"] == registered["user"]["id"]
    assert body["access_token"] != registered["access_token"]
    second = refresh_cookie(api)
    assert second is not None and second != first
    assert second not in response.text

    rows = {row.token_hash: row for row in await _rows(db_session, user_id)}
    assert len(rows) == 2
    old = rows[hash_refresh_token(first)]
    new = rows[hash_refresh_token(second)]
    assert old.revoked_at is not None and new.revoked_at is None
    assert new.family_id == old.family_id == old.id
    assert new.parent_id == old.id

    # The new access token works; the new refresh token works once more.
    assert (
        await api.get(ME_URL, headers=bearer(body["access_token"]))
    ).status_code == HTTPStatus.OK
    assert (await refresh(api)).status_code == HTTPStatus.OK


async def test_refresh_without_cookie_is_401(api: AsyncClient) -> None:
    await register(api)
    api.cookies.clear()
    response = await refresh(api)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert error_code(response) == "INVALID_REFRESH_TOKEN"


async def test_unknown_token_is_401_and_clears_the_cookie(api: AsyncClient) -> None:
    await register(api)
    set_refresh_cookie(api, "definitely-not-a-token-we-issued")
    response = await refresh(api)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert error_code(response) == "INVALID_REFRESH_TOKEN"
    assert 'sokowise_refresh=""' in response.headers["set-cookie"]
    assert refresh_cookie(api) is None


async def test_reusing_a_rotated_token_revokes_the_whole_family(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api)).json()
    user_id = uuid.UUID(registered["user"]["id"])
    stolen = refresh_cookie(api)
    assert stolen is not None

    # Legitimate client rotates twice; the attacker replays the very first token.
    assert (await refresh(api)).status_code == HTTPStatus.OK
    assert (await refresh(api)).status_code == HTTPStatus.OK
    current = refresh_cookie(api)
    assert current is not None

    set_refresh_cookie(api, stolen)
    replay = await refresh(api)
    assert replay.status_code == HTTPStatus.UNAUTHORIZED
    assert error_code(replay) == "INVALID_REFRESH_TOKEN"

    rows = await _rows(db_session, user_id)
    assert len(rows) == 3
    assert all(row.revoked_at is not None for row in rows)
    assert len({row.family_id for row in rows}) == 1

    # The legitimate client's current token is dead too: both parties must log in again.
    set_refresh_cookie(api, current)
    assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED


async def test_reuse_revocation_is_committed_even_though_the_request_fails(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api)).json()
    first = refresh_cookie(api)
    assert first is not None
    assert (await refresh(api)).status_code == HTTPStatus.OK
    live_before = [
        r
        for r in await _rows(db_session, uuid.UUID(registered["user"]["id"]))
        if r.revoked_at is None
    ]
    assert len(live_before) == 1
    set_refresh_cookie(api, first)
    assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED
    live_after = [
        r
        for r in await _rows(db_session, uuid.UUID(registered["user"]["id"]))
        if r.revoked_at is None
    ]
    assert live_after == []


async def test_families_are_independent(api: AsyncClient, db_session: AsyncSession) -> None:
    """Replaying a token from one login does not touch another login's family."""
    registered = (await register(api, phone="+254700555111")).json()
    phone_a = refresh_cookie(api)
    assert phone_a is not None
    api.cookies.clear()
    from tests.db.auth_helpers import login

    assert (await login(api, "+254700555111")).status_code == HTTPStatus.OK
    laptop = refresh_cookie(api)
    assert laptop is not None and laptop != phone_a

    # Rotate the phone's token, then replay its old value: only the phone's family dies.
    set_refresh_cookie(api, phone_a)
    assert (await refresh(api)).status_code == HTTPStatus.OK
    set_refresh_cookie(api, phone_a)
    assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED

    rows = await _rows(db_session, uuid.UUID(registered["user"]["id"]))
    families = {row.family_id for row in rows}
    assert len(families) == 2
    set_refresh_cookie(api, laptop)
    assert (await refresh(api)).status_code == HTTPStatus.OK


async def test_expired_token_is_rejected_without_revoking_the_family(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api)).json()
    token = refresh_cookie(api)
    assert token is not None
    row = (await _rows(db_session, uuid.UUID(registered["user"]["id"])))[0]
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    response = await refresh(api)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    await db_session.refresh(row)
    assert row.revoked_at is None  # expired, not reused: nothing to punish


async def test_refresh_for_a_deactivated_user_revokes_the_family(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api)).json()
    user = await db_session.get(User, uuid.UUID(registered["user"]["id"]))
    assert user is not None
    user.is_active = False
    await db_session.flush()
    assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED
    rows = await _rows(db_session, user.id)
    assert all(row.revoked_at is not None for row in rows)


async def test_refresh_while_business_inactive_is_403_and_keeps_the_session(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api)).json()
    business_id = uuid.UUID(registered["business"]["id"])
    token = refresh_cookie(api)
    assert token is not None
    await set_business_active(db_session, business_id, False)
    response = await refresh(api)
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert error_code(response) == "BUSINESS_INACTIVE"
    # The token was not consumed: reactivating the business lets the same cookie refresh.
    await set_business_active(db_session, business_id, True)
    assert refresh_cookie(api) == token
    assert (await refresh(api)).status_code == HTTPStatus.OK


async def test_refresh_response_reports_must_change_password(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api)).json()
    user = await db_session.get(User, uuid.UUID(registered["user"]["id"]))
    assert user is not None
    user.must_change_password = True
    await db_session.flush()
    response = await refresh(api)
    assert response.status_code == HTTPStatus.OK
    assert response.json()["user"]["must_change_password"] is True


async def test_refresh_is_rate_limited_per_ip(api_factory: ApiFactory) -> None:
    api = await api_factory(rate_limit_refresh_per_minute=2)
    await register(api)
    assert (await refresh(api)).status_code == HTTPStatus.OK
    assert (await refresh(api)).status_code == HTTPStatus.OK
    blocked = await refresh(api)
    assert blocked.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert error_code(blocked) == "RATE_LIMITED"


async def test_refresh_token_is_bound_to_the_auth_path(api: AsyncClient) -> None:
    """The cookie is scoped to /api/v1/auth, so business endpoints never receive it."""
    response = await register(api)
    set_cookie = response.headers["set-cookie"].lower()
    assert "path=/api/v1/auth" in set_cookie
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=lax" in set_cookie
    assert f"max-age={30 * 24 * 3600}" in set_cookie
    assert set_cookie.startswith(f"{REFRESH_COOKIE_NAME}=")


async def test_refresh_ignores_a_bearer_token_and_needs_the_cookie(api: AsyncClient) -> None:
    registered = (await register(api)).json()
    api.cookies.clear()
    response = await api.post(
        REFRESH_URL, headers={**CSRF_HEADERS, **bearer(registered["access_token"])}
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED
