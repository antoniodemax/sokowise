"""The authentication chain and role guards (ARCHITECTURE §3.3, §5.3, §5.4).

Uses `GET /auth/me` (full chain) plus throwaway probe routes for the role guards,
since no OWNER-only business endpoint exists until Phase 4.
"""

import uuid
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import jwt
import pytest
from app.api.deps import require_member, require_owner
from app.core.config import Settings
from app.core.context import BusinessContext
from app.core.tokens import create_access_token
from app.models import BusinessMembership, User
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import (
    ME_URL,
    add_staff,
    bearer,
    error_code,
    login,
    register,
    set_business_active,
)

pytestmark = [pytest.mark.db, pytest.mark.anyio]

OWNER_ONLY_URL = "/_probe/owner-only"
ANY_MEMBER_URL = "/_probe/any-member"


def _mount_probe_routes(api: AsyncClient) -> None:
    transport = api._transport
    assert isinstance(transport, ASGITransport)
    app = transport.app
    assert isinstance(app, FastAPI)
    router = APIRouter(prefix="/_probe")

    @router.get("/owner-only")
    async def owner_only(ctx: BusinessContext = Depends(require_owner)) -> dict[str, str]:  # noqa: B008
        return {"role": ctx.role.value, "business_id": str(ctx.business_id)}

    @router.get("/any-member")
    async def any_member(ctx: BusinessContext = Depends(require_member)) -> dict[str, str]:  # noqa: B008
        return {"role": ctx.role.value, "business_id": str(ctx.business_id)}

    app.include_router(router)


def _settings(api: AsyncClient) -> Settings:
    transport = api._transport
    assert isinstance(transport, ASGITransport)
    settings: Settings = transport.app.state.settings  # type: ignore[attr-defined]
    return settings


def _mint(settings: Settings, user_id: uuid.UUID, business_id: uuid.UUID, **claims: object) -> str:
    token, _ = create_access_token(settings, user_id=user_id, business_id=business_id)
    payload = jwt.decode(token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"])
    payload.update(claims)
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


# --- access tokens -------------------------------------------------------------------


async def test_me_returns_the_verified_identity(api: AsyncClient) -> None:
    registered = (await register(api)).json()
    response = await api.get(ME_URL, headers=bearer(registered["access_token"]))
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert set(body) == {"user", "business", "role", "is_platform_admin"}
    assert body["user"]["id"] == registered["user"]["id"]
    assert body["business"]["id"] == registered["business"]["id"]
    assert body["role"] == "OWNER"


async def test_missing_token_is_401(api: AsyncClient) -> None:
    response = await api.get(ME_URL)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert error_code(response) == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Bearer not.a.jwt"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Token abc"},
    ],
)
async def test_malformed_or_wrong_scheme_is_401(api: AsyncClient, header: dict[str, str]) -> None:
    response = await api.get(ME_URL, headers=header)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert error_code(response) == "UNAUTHORIZED"


async def test_expired_token_is_401(api: AsyncClient) -> None:
    registered = (await register(api)).json()
    settings = _settings(api)
    token, _ = create_access_token(
        settings,
        user_id=uuid.UUID(registered["user"]["id"]),
        business_id=uuid.UUID(registered["business"]["id"]),
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    response = await api.get(ME_URL, headers=bearer(token))
    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_token_with_wrong_signature_is_401(api: AsyncClient) -> None:
    registered = (await register(api)).json()
    other = Settings(jwt_secret="another-secret-that-is-also-32-chars-long")  # noqa: S106
    token, _ = create_access_token(
        other,
        user_id=uuid.UUID(registered["user"]["id"]),
        business_id=uuid.UUID(registered["business"]["id"]),
    )
    response = await api.get(ME_URL, headers=bearer(token))
    assert response.status_code == HTTPStatus.UNAUTHORIZED


async def test_wrong_token_type_is_401(api: AsyncClient) -> None:
    registered = (await register(api)).json()
    token = _mint(
        _settings(api),
        uuid.UUID(registered["user"]["id"]),
        uuid.UUID(registered["business"]["id"]),
        typ="refresh",
    )
    assert (await api.get(ME_URL, headers=bearer(token))).status_code == HTTPStatus.UNAUTHORIZED


async def test_token_for_a_deleted_or_deactivated_user_is_401(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    registered = (await register(api)).json()
    user = await db_session.get(User, uuid.UUID(registered["user"]["id"]))
    assert user is not None
    user.is_active = False
    await db_session.flush()
    response = await api.get(ME_URL, headers=bearer(registered["access_token"]))
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    # A well-formed token for a user that does not exist at all.
    ghost = _mint(_settings(api), uuid.uuid4(), uuid.UUID(registered["business"]["id"]))
    assert (await api.get(ME_URL, headers=bearer(ghost))).status_code == HTTPStatus.UNAUTHORIZED


# --- role comes from the membership, never the token ---------------------------------


async def test_role_claim_in_the_token_is_ignored(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    _mount_probe_routes(api)
    owner = (await register(api)).json()
    business_id = uuid.UUID(owner["business"]["id"])
    staff = await add_staff(db_session, business_id)
    # A token that *claims* OWNER (and even a permissions list) for a STAFF user.
    forged = _mint(
        _settings(api), staff.id, business_id, role="OWNER", permissions=["*"], is_admin=True
    )
    response = await api.get(OWNER_ONLY_URL, headers=bearer(forged))
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert error_code(response) == "FORBIDDEN"
    me = await api.get(ME_URL, headers=bearer(forged))
    assert me.status_code == HTTPStatus.OK and me.json()["role"] == "STAFF"


async def test_demotion_takes_effect_on_the_next_request(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    _mount_probe_routes(api)
    owner = (await register(api)).json()
    token = owner["access_token"]
    assert (await api.get(OWNER_ONLY_URL, headers=bearer(token))).status_code == HTTPStatus.OK
    membership = (
        await db_session.scalars(
            select(BusinessMembership).where(
                BusinessMembership.user_id == uuid.UUID(owner["user"]["id"])
            )
        )
    ).one()
    membership.role = "STAFF"  # type: ignore[assignment]
    await db_session.flush()
    # Same token, no re-login: the role is re-read from the membership row.
    assert (
        await api.get(OWNER_ONLY_URL, headers=bearer(token))
    ).status_code == HTTPStatus.FORBIDDEN


# --- role guards -----------------------------------------------------------------------


async def test_owner_passes_both_guards(api: AsyncClient) -> None:
    _mount_probe_routes(api)
    token = (await register(api)).json()["access_token"]
    assert (await api.get(OWNER_ONLY_URL, headers=bearer(token))).status_code == HTTPStatus.OK
    assert (await api.get(ANY_MEMBER_URL, headers=bearer(token))).status_code == HTTPStatus.OK


async def test_staff_passes_member_guard_but_not_owner_guard(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    _mount_probe_routes(api)
    owner = (await register(api)).json()
    staff = await add_staff(db_session, uuid.UUID(owner["business"]["id"]), phone="+254700444111")
    token = (await login(api, "+254700444111")).json()["access_token"]
    member = await api.get(ANY_MEMBER_URL, headers=bearer(token))
    assert member.status_code == HTTPStatus.OK
    assert member.json() == {"role": "STAFF", "business_id": owner["business"]["id"]}
    denied = await api.get(OWNER_ONLY_URL, headers=bearer(token))
    assert denied.status_code == HTTPStatus.FORBIDDEN
    assert error_code(denied) == "FORBIDDEN"
    assert str(staff.id) not in denied.text


async def test_guards_reject_unauthenticated_requests(api: AsyncClient) -> None:
    _mount_probe_routes(api)
    assert (await api.get(OWNER_ONLY_URL)).status_code == HTTPStatus.UNAUTHORIZED
    assert (await api.get(ANY_MEMBER_URL)).status_code == HTTPStatus.UNAUTHORIZED


# --- business status -------------------------------------------------------------------


async def test_active_business_request_succeeds(api: AsyncClient) -> None:
    token = (await register(api)).json()["access_token"]
    assert (await api.get(ME_URL, headers=bearer(token))).status_code == HTTPStatus.OK


async def test_business_deactivated_after_login_is_rejected(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    _mount_probe_routes(api)
    registered = (await register(api)).json()
    token = registered["access_token"]
    assert (await api.get(ME_URL, headers=bearer(token))).status_code == HTTPStatus.OK
    await set_business_active(db_session, uuid.UUID(registered["business"]["id"]), False)
    for url in (ME_URL, OWNER_ONLY_URL, ANY_MEMBER_URL):
        response = await api.get(url, headers=bearer(token))
        assert response.status_code == HTTPStatus.FORBIDDEN, url
        assert error_code(response) == "BUSINESS_INACTIVE"
    # Reactivation restores access to the same session.
    await set_business_active(db_session, uuid.UUID(registered["business"]["id"]), True)
    assert (await api.get(ME_URL, headers=bearer(token))).status_code == HTTPStatus.OK


async def test_membership_deactivated_after_login_is_rejected(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    owner = (await register(api)).json()
    await add_staff(db_session, uuid.UUID(owner["business"]["id"]), phone="+254700444222")
    token = (await login(api, "+254700444222")).json()["access_token"]
    assert (await api.get(ME_URL, headers=bearer(token))).status_code == HTTPStatus.OK
    membership = (
        await db_session.scalars(
            select(BusinessMembership).where(
                BusinessMembership.business_id == uuid.UUID(owner["business"]["id"]),
                BusinessMembership.role == "STAFF",
            )
        )
    ).one()
    membership.is_active = False
    await db_session.flush()
    response = await api.get(ME_URL, headers=bearer(token))
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert error_code(response) == "MEMBERSHIP_INACTIVE"


# --- tenant isolation ------------------------------------------------------------------


async def test_token_cannot_be_pointed_at_another_business(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    _mount_probe_routes(api)
    alice = (await register(api, business_name="Alice Duka")).json()
    bob = (await register(api, business_name="Bob Duka")).json()
    # A token that names Bob's business for Alice's user id (signed with the real key,
    # i.e. worse than anything a client could produce).
    forged = _mint(_settings(api), uuid.UUID(alice["user"]["id"]), uuid.UUID(bob["business"]["id"]))
    # Cross-tenant: 404, never 403, so the response does not confirm Bob's business exists
    # (ARCHITECTURE §8; changed from 401 in Phase 4).
    for url in (ME_URL, OWNER_ONLY_URL, ANY_MEMBER_URL):
        response = await api.get(url, headers=bearer(forged))
        assert response.status_code == HTTPStatus.NOT_FOUND, url
        assert error_code(response) == "NOT_FOUND"
        assert "Bob" not in response.text
    # A selector for a business that does not exist at all looks exactly the same.
    ghost = _mint(_settings(api), uuid.UUID(alice["user"]["id"]), uuid.uuid4())
    response = await api.get(ME_URL, headers=bearer(ghost))
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert error_code(response) == "NOT_FOUND"
    # A genuine token still resolves to Alice's own business only.
    me = await api.get(ME_URL, headers=bearer(alice["access_token"]))
    assert me.json()["business"]["id"] == alice["business"]["id"]


async def test_business_id_in_query_or_body_is_ignored(api: AsyncClient) -> None:
    _mount_probe_routes(api)
    alice = (await register(api, business_name="Alice Duka")).json()
    bob = (await register(api, business_name="Bob Duka")).json()
    response = await api.get(
        ANY_MEMBER_URL,
        headers=bearer(alice["access_token"]),
        params={"business_id": bob["business"]["id"]},
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["business_id"] == alice["business"]["id"]


async def test_business_context_is_built_from_the_membership_row(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    _mount_probe_routes(api)
    owner = (await register(api, timezone="Africa/Kampala")).json()
    response = await api.get(OWNER_ONLY_URL, headers=bearer(owner["access_token"]))
    assert response.json() == {"role": "OWNER", "business_id": owner["business"]["id"]}
    membership = (
        await db_session.scalars(
            select(BusinessMembership).where(
                BusinessMembership.user_id == uuid.UUID(owner["user"]["id"])
            )
        )
    ).one()
    assert membership.business_id == uuid.UUID(owner["business"]["id"])
