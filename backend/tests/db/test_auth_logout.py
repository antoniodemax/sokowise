"""POST /api/v1/auth/logout and /logout-all (PRD FR-B3, ARCHITECTURE §5.1)."""

import uuid
from http import HTTPStatus

import pytest
from app.models import RefreshToken
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import (
    CSRF_HEADERS,
    LOGOUT_ALL_URL,
    LOGOUT_URL,
    ME_URL,
    bearer,
    login,
    refresh,
    refresh_cookie,
    register,
    set_refresh_cookie,
)

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def _live_tokens(session: AsyncSession, user_id: uuid.UUID) -> int:
    rows = await session.scalars(
        select(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .execution_options(populate_existing=True)
    )
    return len(list(rows))


async def test_logout_revokes_the_session_and_clears_the_cookie(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api)).json()
    user_id = uuid.UUID(registered["user"]["id"])
    token = refresh_cookie(api)
    assert token is not None
    assert await _live_tokens(db_session, user_id) == 1

    response = await api.post(LOGOUT_URL, headers=CSRF_HEADERS)
    assert response.status_code == HTTPStatus.NO_CONTENT
    assert response.content == b""
    assert 'sokowise_refresh=""' in response.headers["set-cookie"]
    assert refresh_cookie(api) is None
    assert await _live_tokens(db_session, user_id) == 0

    # The server-side token is unusable even if the client kept a copy.
    set_refresh_cookie(api, token)
    assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED


async def test_logout_revokes_the_whole_family_not_just_the_latest_token(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api)).json()
    first = refresh_cookie(api)
    assert (await refresh(api)).status_code == HTTPStatus.OK
    assert (await api.post(LOGOUT_URL, headers=CSRF_HEADERS)).status_code == HTTPStatus.NO_CONTENT
    assert await _live_tokens(db_session, uuid.UUID(registered["user"]["id"])) == 0
    assert first is not None
    set_refresh_cookie(api, first)
    assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED


async def test_logout_is_idempotent(api: AsyncClient) -> None:
    await register(api)
    token = refresh_cookie(api)
    assert token is not None
    assert (await api.post(LOGOUT_URL, headers=CSRF_HEADERS)).status_code == HTTPStatus.NO_CONTENT
    # Again with the same (now revoked) cookie, and again with no cookie at all.
    set_refresh_cookie(api, token)
    assert (await api.post(LOGOUT_URL, headers=CSRF_HEADERS)).status_code == HTTPStatus.NO_CONTENT
    api.cookies.clear()
    assert (await api.post(LOGOUT_URL, headers=CSRF_HEADERS)).status_code == HTTPStatus.NO_CONTENT
    set_refresh_cookie(api, "never-issued")
    assert (await api.post(LOGOUT_URL, headers=CSRF_HEADERS)).status_code == HTTPStatus.NO_CONTENT


async def test_logout_does_not_need_a_bearer_token(api: AsyncClient) -> None:
    """An expired access token must not trap a user in a session they want to end."""
    await register(api)
    response = await api.post(LOGOUT_URL, headers={**CSRF_HEADERS, "Authorization": "Bearer junk"})
    assert response.status_code == HTTPStatus.NO_CONTENT


async def test_logout_leaves_other_sessions_alone(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api, phone="+254700666111")).json()
    api.cookies.clear()
    assert (await login(api, "+254700666111")).status_code == HTTPStatus.OK
    laptop = refresh_cookie(api)
    assert (await api.post(LOGOUT_URL, headers=CSRF_HEADERS)).status_code == HTTPStatus.NO_CONTENT
    assert await _live_tokens(db_session, uuid.UUID(registered["user"]["id"])) == 1
    assert laptop is not None
    set_refresh_cookie(api, laptop)
    assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED  # the one we logged out
    # The first (phone) session was untouched.
    assert await _live_tokens(db_session, uuid.UUID(registered["user"]["id"])) == 1


async def test_logout_all_revokes_every_session(api: AsyncClient, db_session: AsyncSession) -> None:
    registered = (await register(api, phone="+254700666222")).json()
    phone = refresh_cookie(api)
    api.cookies.clear()
    laptop_session = (await login(api, "+254700666222")).json()
    laptop = refresh_cookie(api)
    assert await _live_tokens(db_session, uuid.UUID(registered["user"]["id"])) == 2

    response = await api.post(LOGOUT_ALL_URL, headers=bearer(laptop_session["access_token"]))
    assert response.status_code == HTTPStatus.NO_CONTENT
    assert await _live_tokens(db_session, uuid.UUID(registered["user"]["id"])) == 0
    for token in (phone, laptop):
        assert token is not None
        set_refresh_cookie(api, token)
        assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED
    # Access tokens stay valid until they expire (15 min); nothing here revokes them.
    assert (
        await api.get(ME_URL, headers=bearer(laptop_session["access_token"]))
    ).status_code == HTTPStatus.OK


async def test_logout_all_requires_authentication(api: AsyncClient) -> None:
    await register(api)
    assert (await api.post(LOGOUT_ALL_URL)).status_code == HTTPStatus.UNAUTHORIZED
