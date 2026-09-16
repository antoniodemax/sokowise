"""POST /api/v1/auth/change-password and the must_change_password gate (ARCHITECTURE §3.3 3a)."""

import uuid
from http import HTTPStatus

import pytest
from app.core.passwords import verify_password
from app.models import RefreshToken, User
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import (
    CHANGE_PASSWORD_URL,
    CSRF_HEADERS,
    LOGOUT_ALL_URL,
    LOGOUT_URL,
    ME_URL,
    OTHER_PASSWORD,
    PASSWORD,
    add_staff,
    bearer,
    error_code,
    login,
    refresh,
    refresh_cookie,
    register,
    set_refresh_cookie,
)
from tests.db.conftest import ApiFactory

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def _change(api: AsyncClient, token: str, current: str, new: str) -> Response:
    return await api.post(
        CHANGE_PASSWORD_URL,
        headers=bearer(token),
        json={"current_password": current, "new_password": new},
    )


async def test_change_password_rehashes_and_replaces_sessions(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api, phone="+254700777111")).json()
    user_id = uuid.UUID(registered["user"]["id"])
    old_cookie = refresh_cookie(api)
    user = await db_session.get(User, user_id)
    assert user is not None
    old_hash = user.password_hash

    response = await api.post(
        CHANGE_PASSWORD_URL,
        headers=bearer(registered["access_token"]),
        json={"current_password": PASSWORD, "new_password": OTHER_PASSWORD},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert body["user"]["must_change_password"] is False
    assert body["access_token"] != registered["access_token"]
    assert OTHER_PASSWORD not in response.text and PASSWORD not in response.text

    await db_session.refresh(user)
    assert user.password_hash != old_hash
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(user.password_hash, OTHER_PASSWORD)
    assert not verify_password(user.password_hash, PASSWORD)

    # Old refresh token dead, new one alive.
    new_cookie = refresh_cookie(api)
    assert new_cookie is not None and new_cookie != old_cookie
    assert old_cookie is not None
    set_refresh_cookie(api, old_cookie)
    assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED
    set_refresh_cookie(api, new_cookie)
    assert (await refresh(api)).status_code == HTTPStatus.OK

    # Old password no longer logs in; the new one does.
    assert (await login(api, "+254700777111", PASSWORD)).status_code == HTTPStatus.UNAUTHORIZED
    assert (await login(api, "+254700777111", OTHER_PASSWORD)).status_code == HTTPStatus.OK


async def test_change_password_logs_out_other_devices(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api, phone="+254700777222")).json()
    phone_cookie = refresh_cookie(api)
    api.cookies.clear()
    laptop = (await login(api, "+254700777222")).json()
    response = await _change(api, laptop["access_token"], PASSWORD, OTHER_PASSWORD)
    assert response.status_code == HTTPStatus.OK
    live = await db_session.scalars(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == uuid.UUID(registered["user"]["id"]),
            RefreshToken.revoked_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    assert len(list(live)) == 1  # only the session issued by change-password
    assert phone_cookie is not None
    set_refresh_cookie(api, phone_cookie)
    assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED


async def test_wrong_current_password_is_rejected_and_changes_nothing(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api)).json()
    cookie = refresh_cookie(api)
    response = await api.post(
        CHANGE_PASSWORD_URL,
        headers=bearer(registered["access_token"]),
        json={"current_password": "not my password", "new_password": OTHER_PASSWORD},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert error_code(response) == "INVALID_CURRENT_PASSWORD"
    user = await db_session.get(User, uuid.UUID(registered["user"]["id"]))
    assert user is not None and verify_password(user.password_hash, PASSWORD)
    assert refresh_cookie(api) == cookie
    assert (await refresh(api)).status_code == HTTPStatus.OK  # session untouched


@pytest.mark.parametrize("new_password", ["short", "password123", PASSWORD, "x" * 129])
async def test_weak_or_unchanged_new_password_is_a_validation_error(
    api: AsyncClient, new_password: str
) -> None:
    registered = (await register(api)).json()
    response = await api.post(
        CHANGE_PASSWORD_URL,
        headers=bearer(registered["access_token"]),
        json={"current_password": PASSWORD, "new_password": new_password},
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert error_code(response) == "VALIDATION_ERROR"
    assert new_password not in response.text


async def test_change_password_requires_authentication(api: AsyncClient) -> None:
    await register(api)
    response = await api.post(
        CHANGE_PASSWORD_URL, json={"current_password": PASSWORD, "new_password": OTHER_PASSWORD}
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_change_password_is_rate_limited_per_user(api_factory: ApiFactory) -> None:
    api = await api_factory(rate_limit_password_change_per_minute=2)
    token = (await register(api)).json()["access_token"]
    for _ in range(2):
        bad = await _change(api, token, "wrong current", OTHER_PASSWORD)
        assert bad.status_code == HTTPStatus.BAD_REQUEST
    blocked = await _change(api, token, PASSWORD, OTHER_PASSWORD)
    assert blocked.status_code == HTTPStatus.TOO_MANY_REQUESTS


# --- must_change_password ---------------------------------------------------------


async def test_must_change_password_blocks_everything_but_the_password_change(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    owner = (await register(api)).json()
    staff = await add_staff(
        db_session,
        uuid.UUID(owner["business"]["id"]),
        phone="+254700777333",
        must_change_password=True,
    )
    api.cookies.clear()
    session = (await login(api, "+254700777333")).json()
    assert session["user"]["must_change_password"] is True  # login itself succeeds
    token = session["access_token"]

    me = await api.get(ME_URL, headers=bearer(token))
    assert me.status_code == HTTPStatus.FORBIDDEN
    assert error_code(me) == "PASSWORD_CHANGE_REQUIRED"

    # Refresh keeps the session alive while the user is on the change-password screen.
    assert (await refresh(api)).status_code == HTTPStatus.OK

    changed = await api.post(
        CHANGE_PASSWORD_URL,
        headers=bearer(token),
        json={"current_password": PASSWORD, "new_password": OTHER_PASSWORD},
    )
    assert changed.status_code == HTTPStatus.OK, changed.text
    assert changed.json()["user"]["must_change_password"] is False
    await db_session.refresh(staff)
    flag_after = staff.must_change_password
    assert flag_after is False

    # The gate lifts immediately, even for the access token issued before the change.
    assert (await api.get(ME_URL, headers=bearer(token))).status_code == HTTPStatus.OK
    new_token = changed.json()["access_token"]
    assert (await api.get(ME_URL, headers=bearer(new_token))).status_code == HTTPStatus.OK


async def test_must_change_password_still_allows_logout(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    owner = (await register(api)).json()
    await add_staff(
        db_session,
        uuid.UUID(owner["business"]["id"]),
        phone="+254700777444",
        must_change_password=True,
    )
    api.cookies.clear()
    token = (await login(api, "+254700777444")).json()["access_token"]
    assert (
        await api.post(LOGOUT_ALL_URL, headers=bearer(token))
    ).status_code == HTTPStatus.NO_CONTENT
    assert (await api.post(LOGOUT_URL, headers=CSRF_HEADERS)).status_code == HTTPStatus.NO_CONTENT


async def test_role_guards_also_enforce_the_password_gate(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    """The gate sits in get_business_context, so every business route inherits it."""
    owner = (await register(api)).json()
    user = await db_session.get(User, uuid.UUID(owner["user"]["id"]))
    assert user is not None
    user.must_change_password = True
    await db_session.flush()
    response = await api.get(ME_URL, headers=bearer(owner["access_token"]))
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert error_code(response) == "PASSWORD_CHANGE_REQUIRED"
