"""/api/v1/users — member management (PRD FR-C1, FR-C2, FR-B6; DATA_MAPPING §3.3)."""

import json
import uuid
from http import HTTPStatus

import pytest
from app.api.deps import get_business_context, get_current_user
from app.core.config import Settings
from app.core.passwords import verify_password
from app.core.tokens import decode_access_token
from app.models import AuditLog, BusinessMembership, RefreshToken, User
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import (
    ME_URL,
    OTHER_PASSWORD,
    PASSWORD,
    add_staff,
    bearer,
    error_code,
    login,
    set_business_active,
    unique_phone,
)
from tests.db.isolation import Tenant

pytestmark = [pytest.mark.db, pytest.mark.anyio]

URL = "/api/v1/users"


def _staff_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "full_name": "New Staff",
        "phone": unique_phone(),
        "password": PASSWORD,
    }
    payload.update(overrides)
    return payload


async def _audit_rows(session: AsyncSession, business_id: str) -> list[AuditLog]:
    result = await session.scalars(
        select(AuditLog)
        .where(AuditLog.business_id == uuid.UUID(business_id))
        .order_by(AuditLog.created_at, AuditLog.id)
        .execution_options(populate_existing=True)
    )
    return list(result)


def _events(rows: list[AuditLog]) -> set[tuple[str, str, str]]:
    return {(r.action, json.dumps(r.before), json.dumps(r.after)) for r in rows}


async def _live_tokens(session: AsyncSession, user_id: str) -> int:
    rows = await session.scalars(
        select(RefreshToken)
        .where(RefreshToken.user_id == uuid.UUID(user_id), RefreshToken.revoked_at.is_(None))
        .execution_options(populate_existing=True)
    )
    return len(list(rows))


# --- list / get --------------------------------------------------------------------------


async def test_owner_lists_members_of_own_business_only(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    response = await api.get(URL, headers=a.owner)
    assert response.status_code == HTTPStatus.OK, response.text
    members = response.json()
    assert {m["user_id"] for m in members} == {a.owner_user_id, a.staff_user_id}
    assert {m["role"] for m in members} == {"OWNER", "STAFF"}
    assert b.owner_user_id not in response.text
    assert b.staff_user_id is not None and b.staff_user_id not in response.text
    owner = next(m for m in members if m["role"] == "OWNER")
    assert set(owner) == {
        "user_id",
        "full_name",
        "phone",
        "email",
        "role",
        "is_active",
        "must_change_password",
        "last_login_at",
        "joined_at",
    }
    assert "password" not in response.text.lower().replace("must_change_password", "")


async def test_staff_cannot_manage_users(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    assert a.staff is not None and a.staff_user_id is not None
    calls = [
        api.get(URL, headers=a.staff),
        api.post(URL, headers=a.staff, json=_staff_payload()),
        api.get(f"{URL}/{a.owner_user_id}", headers=a.staff),
        api.patch(f"{URL}/{a.staff_user_id}", headers=a.staff, json={"role": "OWNER"}),
        api.patch(f"{URL}/{a.owner_user_id}", headers=a.staff, json={"is_active": False}),
        api.post(
            f"{URL}/{a.owner_user_id}/reset-password",
            headers=a.staff,
            json={"password": OTHER_PASSWORD},
        ),
    ]
    for call in calls:
        response = await call
        assert response.status_code == HTTPStatus.FORBIDDEN, response.text
        assert error_code(response) == "FORBIDDEN"
    # Still STAFF, owner still an active owner.
    me = await api.get(ME_URL, headers=a.staff)
    assert me.json()["role"] == "STAFF"
    assert (await api.get(ME_URL, headers=a.owner)).json()["role"] == "OWNER"


async def test_unauthenticated_is_401(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    assert (await api.get(URL)).status_code == HTTPStatus.UNAUTHORIZED
    assert (await api.post(URL, json=_staff_payload())).status_code == HTTPStatus.UNAUTHORIZED
    assert (await api.get(f"{URL}/{a.owner_user_id}")).status_code == HTTPStatus.UNAUTHORIZED


async def test_unknown_and_foreign_users_are_404(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    for user_id in (uuid.uuid4(), b.owner_user_id, b.staff_user_id):
        for call in (
            api.get(f"{URL}/{user_id}", headers=a.owner),
            api.patch(f"{URL}/{user_id}", headers=a.owner, json={"is_active": False}),
            api.post(
                f"{URL}/{user_id}/reset-password", headers=a.owner, json={"password": PASSWORD}
            ),
        ):
            response = await call
            assert response.status_code == HTTPStatus.NOT_FOUND, response.text
            assert error_code(response) == "NOT_FOUND"
    assert (await api.get(f"{URL}/not-a-uuid", headers=a.owner)).status_code == (
        HTTPStatus.UNPROCESSABLE_ENTITY
    )


# --- create staff ------------------------------------------------------------------------


async def test_owner_creates_staff_who_must_change_password(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    phone = unique_phone()
    response = await api.post(
        URL, headers=a.owner, json=_staff_payload(phone=phone, email="Staff@Example.com")
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    body = response.json()
    assert body["role"] == "STAFF"
    assert body["is_active"] is True
    assert body["must_change_password"] is True
    assert body["email"] == "staff@example.com"
    assert PASSWORD not in response.text and "password_hash" not in response.text

    user = await db_session.get(User, uuid.UUID(body["user_id"]))
    assert user is not None and user.password_hash is not None
    assert verify_password(user.password_hash, PASSWORD)
    membership = (
        await db_session.scalars(
            select(BusinessMembership).where(BusinessMembership.user_id == user.id)
        )
    ).one()
    assert membership.business_id == uuid.UUID(a.business_id)
    assert membership.role.value == "STAFF"

    # First login works but everything business-scoped is gated until the password changes.
    session = await login(api, phone)
    assert session.status_code == HTTPStatus.OK
    assert session.json()["user"]["must_change_password"] is True
    gated = await api.get(ME_URL, headers=bearer(session.json()["access_token"]))
    assert gated.status_code == HTTPStatus.FORBIDDEN
    assert error_code(gated) == "PASSWORD_CHANGE_REQUIRED"

    rows = await _audit_rows(db_session, a.business_id)
    assert [r.action for r in rows] == ["user.create"]
    assert rows[0].entity_type == "user" and rows[0].entity_id == user.id
    assert rows[0].actor_user_id == uuid.UUID(a.owner_user_id)
    assert rows[0].after == {"role": "STAFF", "is_active": True}
    assert rows[0].before is None


async def test_create_staff_cannot_choose_a_role(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    response = await api.post(URL, headers=a.owner, json=_staff_payload(role="OWNER"))
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    response = await api.post(
        URL, headers=a.owner, json=_staff_payload(business_id=str(uuid.uuid4()))
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_existing_phone_is_a_409_and_creates_nothing(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    b_owner = await db_session.get(User, uuid.UUID(b.owner_user_id))
    assert b_owner is not None
    response = await api.post(URL, headers=a.owner, json=_staff_payload(phone=b_owner.phone))
    assert response.status_code == HTTPStatus.CONFLICT
    assert error_code(response) == "ACCOUNT_EXISTS"
    assert "Beta" not in response.text  # nothing about the other tenant
    # B's owner was not pulled into A.
    members = (await api.get(URL, headers=a.owner)).json()
    assert b.owner_user_id not in {m["user_id"] for m in members}
    assert await _audit_rows(db_session, a.business_id) == []


@pytest.mark.parametrize(
    "overrides",
    [{"password": "short"}, {"password": "password123"}, {"phone": "12"}, {"full_name": ""}],
)
async def test_invalid_staff_payload_is_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], overrides: dict[str, object]
) -> None:
    a, _ = tenants
    response = await api.post(URL, headers=a.owner, json=_staff_payload(**overrides))
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert error_code(response) == "VALIDATION_ERROR"


# --- role changes and (de)activation ------------------------------------------------------


async def test_owner_promotes_staff_and_demotes_them_again(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    promoted = await api.patch(f"{URL}/{a.staff_user_id}", headers=a.owner, json={"role": "OWNER"})
    assert promoted.status_code == HTTPStatus.OK, promoted.text
    assert promoted.json()["role"] == "OWNER"
    # Takes effect on the next request with the staff member's existing token.
    assert (await api.get(ME_URL, headers=a.staff)).json()["role"] == "OWNER"
    assert (await api.get("/api/v1/business", headers=a.staff)).status_code == HTTPStatus.OK

    demoted = await api.patch(f"{URL}/{a.staff_user_id}", headers=a.owner, json={"role": "STAFF"})
    assert demoted.status_code == HTTPStatus.OK
    assert (await api.get("/api/v1/business", headers=a.staff)).status_code == HTTPStatus.FORBIDDEN

    rows = await _audit_rows(db_session, a.business_id)
    # Order-independent: inside one test transaction every row shares the same now().
    assert _events(rows) == {
        ("user.role_change", '{"role": "STAFF"}', '{"role": "OWNER"}'),
        ("user.role_change", '{"role": "OWNER"}', '{"role": "STAFF"}'),
    }
    assert all(r.entity_id == uuid.UUID(str(a.staff_user_id)) for r in rows)


async def test_deactivating_staff_revokes_sessions_and_blocks_login(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None and a.staff_user_id is not None
    assert await _live_tokens(db_session, a.staff_user_id) == 1
    response = await api.patch(
        f"{URL}/{a.staff_user_id}", headers=a.owner, json={"is_active": False}
    )
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["is_active"] is False

    assert await _live_tokens(db_session, a.staff_user_id) == 0
    gated = await api.get(ME_URL, headers=a.staff)
    assert gated.status_code == HTTPStatus.FORBIDDEN
    assert error_code(gated) == "MEMBERSHIP_INACTIVE"
    staff_user = await db_session.get(User, uuid.UUID(a.staff_user_id))
    assert staff_user is not None
    phone = staff_user.phone
    blocked = await login(api, phone)
    assert blocked.status_code == HTTPStatus.FORBIDDEN
    assert error_code(blocked) == "MEMBERSHIP_INACTIVE"
    # (a failed request rolled the shared session back, which expired `staff_user`)
    await db_session.refresh(staff_user)
    assert staff_user.is_active is True  # the person, not just this membership, is untouched

    reactivated = await api.patch(
        f"{URL}/{a.staff_user_id}", headers=a.owner, json={"is_active": True}
    )
    assert reactivated.status_code == HTTPStatus.OK
    assert (await login(api, phone)).status_code == HTTPStatus.OK

    rows = await _audit_rows(db_session, a.business_id)
    assert _events(rows) == {
        ("user.deactivate", '{"is_active": true}', '{"is_active": false}'),
        ("user.reactivate", '{"is_active": false}', '{"is_active": true}'),
    }


async def test_patch_needs_a_change_and_rejects_unknown_fields(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    for payload in ({}, {"role": "ADMIN"}, {"full_name": "x"}, {"is_active": "maybe"}):
        response = await api.patch(f"{URL}/{a.staff_user_id}", headers=a.owner, json=payload)
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, payload


async def test_no_op_patch_writes_no_audit_row(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    response = await api.patch(f"{URL}/{a.staff_user_id}", headers=a.owner, json={"role": "STAFF"})
    assert response.status_code == HTTPStatus.OK
    assert await _audit_rows(db_session, a.business_id) == []


# --- last-owner protection ---------------------------------------------------------------


async def test_the_last_owner_cannot_demote_or_deactivate_themselves(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    for payload in ({"role": "STAFF"}, {"is_active": False}, {"role": "STAFF", "is_active": False}):
        response = await api.patch(f"{URL}/{a.owner_user_id}", headers=a.owner, json=payload)
        assert response.status_code == HTTPStatus.CONFLICT, payload
        assert error_code(response) == "LAST_OWNER"
    assert (await api.get(ME_URL, headers=a.owner)).json()["role"] == "OWNER"
    assert await _audit_rows(db_session, a.business_id) == []


async def test_an_owner_can_step_down_once_another_owner_exists(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    assert (
        await api.patch(f"{URL}/{a.staff_user_id}", headers=a.owner, json={"role": "OWNER"})
    ).status_code == HTTPStatus.OK
    stepped_down = await api.patch(
        f"{URL}/{a.owner_user_id}", headers=a.owner, json={"role": "STAFF"}
    )
    assert stepped_down.status_code == HTTPStatus.OK
    # The original owner is now STAFF: no more user management for them...
    assert (await api.get(URL, headers=a.owner)).status_code == HTTPStatus.FORBIDDEN
    # ...and the new sole owner is protected in turn.
    last = await api.patch(f"{URL}/{a.staff_user_id}", headers=a.staff, json={"is_active": False})
    assert last.status_code == HTTPStatus.CONFLICT
    assert error_code(last) == "LAST_OWNER"


async def test_an_inactive_owner_does_not_count(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    second_owner = await add_staff(db_session, uuid.UUID(a.business_id))
    membership = (
        await db_session.scalars(
            select(BusinessMembership).where(BusinessMembership.user_id == second_owner.id)
        )
    ).one()
    membership.role = "OWNER"  # type: ignore[assignment]
    membership.is_active = False
    await db_session.flush()
    response = await api.patch(f"{URL}/{a.owner_user_id}", headers=a.owner, json={"role": "STAFF"})
    assert response.status_code == HTTPStatus.CONFLICT
    assert error_code(response) == "LAST_OWNER"


# --- password reset -------------------------------------------------------------------------


async def test_owner_resets_a_staff_password(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None and a.staff_user_id is not None
    staff_user = await db_session.get(User, uuid.UUID(a.staff_user_id))
    assert staff_user is not None
    old_hash = staff_user.password_hash

    response = await api.post(
        f"{URL}/{a.staff_user_id}/reset-password",
        headers=a.owner,
        json={"password": OTHER_PASSWORD},
    )
    assert response.status_code == HTTPStatus.NO_CONTENT, response.text
    await db_session.refresh(staff_user)
    assert staff_user.password_hash != old_hash
    assert staff_user.password_hash is not None
    assert verify_password(staff_user.password_hash, OTHER_PASSWORD)
    assert staff_user.must_change_password is True
    assert await _live_tokens(db_session, a.staff_user_id) == 0
    phone = staff_user.phone

    # Old password dead, new one works but is gated until changed.
    assert (await login(api, phone, PASSWORD)).status_code == HTTPStatus.UNAUTHORIZED
    session = await login(api, phone, OTHER_PASSWORD)
    assert session.status_code == HTTPStatus.OK
    assert session.json()["user"]["must_change_password"] is True

    rows = await _audit_rows(db_session, a.business_id)
    assert [r.action for r in rows] == ["user.password_reset"]
    row = rows[0]
    assert row.before is None and row.after is None
    assert row.entity_id == uuid.UUID(a.staff_user_id)
    assert OTHER_PASSWORD not in str(row.__dict__) and "$argon2" not in str(row.__dict__)


async def test_reset_is_only_for_staff_and_never_for_yourself(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    own = await api.post(
        f"{URL}/{a.owner_user_id}/reset-password", headers=a.owner, json={"password": PASSWORD}
    )
    assert own.status_code == HTTPStatus.FORBIDDEN
    # A second owner is a peer: not resettable either.
    assert (
        await api.patch(f"{URL}/{a.staff_user_id}", headers=a.owner, json={"role": "OWNER"})
    ).status_code == HTTPStatus.OK
    peer = await api.post(
        f"{URL}/{a.staff_user_id}/reset-password", headers=a.owner, json={"password": PASSWORD}
    )
    assert peer.status_code == HTTPStatus.FORBIDDEN
    assert error_code(peer) == "FORBIDDEN"
    weak = await api.post(
        f"{URL}/{a.staff_user_id}/reset-password", headers=a.owner, json={"password": "short"}
    )
    assert weak.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    actions = [r.action for r in await _audit_rows(db_session, a.business_id)]
    assert "user.password_reset" not in actions


# --- lifecycle and audit hygiene -------------------------------------------------------------


async def test_inactive_business_blocks_member_management(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    await set_business_active(db_session, uuid.UUID(a.business_id), False)
    response = await api.get(URL, headers=a.owner)
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert error_code(response) == "BUSINESS_INACTIVE"
    response = await api.post(URL, headers=a.owner, json=_staff_payload())
    assert response.status_code == HTTPStatus.FORBIDDEN


async def test_audit_rows_never_contain_secrets(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    created = await api.post(URL, headers=a.owner, json=_staff_payload(password=OTHER_PASSWORD))
    assert created.status_code == HTTPStatus.CREATED
    user_id = created.json()["user_id"]
    assert (
        await api.post(
            f"{URL}/{user_id}/reset-password", headers=a.owner, json={"password": PASSWORD}
        )
    ).status_code == HTTPStatus.NO_CONTENT
    rows = await _audit_rows(db_session, a.business_id)
    assert len(rows) == 2
    dump = " ".join(f"{r.action} {r.before} {r.after} {r.user_agent} {r.ip}" for r in rows)
    for secret in (PASSWORD, OTHER_PASSWORD, "$argon2", "Bearer ", "eyJ"):
        assert secret not in dump
    assert all(r.actor_user_id == uuid.UUID(a.owner_user_id) for r in rows)
    assert all(r.business_id == uuid.UUID(a.business_id) for r in rows)


async def test_owner_context_carries_the_membership(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """`BusinessContext.membership_id` is the verified row, not something the client sent."""
    a, _ = tenants
    membership = (
        await db_session.scalars(
            select(BusinessMembership).where(
                BusinessMembership.user_id == uuid.UUID(a.owner_user_id)
            )
        )
    ).one()
    token = a.owner["Authorization"].removeprefix("Bearer ")
    claims = decode_access_token(Settings(), token)
    user = await get_current_user(claims, db_session)
    ctx = await get_business_context(claims, user, db_session)
    assert (ctx.user_id, ctx.business_id, ctx.membership_id, ctx.role.value) == (
        uuid.UUID(a.owner_user_id),
        uuid.UUID(a.business_id),
        membership.id,
        "OWNER",
    )
