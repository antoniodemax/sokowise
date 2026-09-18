"""Operator dashboard: allowlisted phones only, platform-wide counts, no tenant detail."""

import uuid
from http import HTTPStatus

import pytest
from app.models import User
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import (
    PASSWORD,
    add_staff,
    bearer,
    error_code,
    login,
    register,
    unique_phone,
)
from tests.db.conftest import ApiFactory
from tests.db.sales_helpers import make_customer, make_product, post_sale, sale_payload

pytestmark = [pytest.mark.db, pytest.mark.anyio]

URL = "/api/v1/admin/overview"


async def _owner(api: AsyncClient, business_name: str, phone: str) -> dict[str, object]:
    response = await register(api, business_name=business_name, phone=phone)
    assert response.status_code == HTTPStatus.CREATED, response.text
    api.cookies.clear()
    body: dict[str, object] = response.json()
    return body


async def test_allowlisted_owner_sees_platform_totals_without_tenant_detail(
    api_factory: ApiFactory, db_session: AsyncSession
) -> None:
    admin_phone = unique_phone()
    api = await api_factory(platform_admin_phones=[admin_phone])
    admin = await _owner(api, "Operator Duka", admin_phone)
    other = await _owner(api, "Beta Duka", unique_phone())
    admin_headers = bearer(str(admin["access_token"]))
    other_headers = bearer(str(other["access_token"]))
    # The session flag is what the frontend uses to show the route.
    assert admin["is_platform_admin"] is True
    assert other["is_platform_admin"] is False

    # Some activity in the other tenant.
    sugar = await make_product(api, other_headers, name="Sugar", price="150", cost="130")
    await make_customer(api, other_headers, name="Mama Njeri")
    sale = await post_sale(
        api, other_headers, sale_payload([(sugar["id"], "2")], [("CASH", "300")])
    )
    assert sale.status_code == HTTPStatus.CREATED, sale.text
    await add_staff(db_session, uuid.UUID(str(other["business"]["id"])), phone=unique_phone())  # type: ignore[index]

    response = await api.get(URL, headers=admin_headers)
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    totals = body["totals"]
    assert totals["businesses"] == 2 and totals["businesses_active"] == 2
    assert totals["users"] == 3 and totals["owners"] == 2 and totals["staff"] == 1
    assert totals["products"] == 1 and totals["customers"] == 1
    assert totals["sales"] == 1 and totals["revenue"] == "300.00"
    assert totals["copilot_messages"] == 0 and totals["proposals_applied"] == 0
    assert body["last_7_days"]["new_businesses"] == 2
    assert body["last_7_days"]["sales"] == 1 and body["last_7_days"]["revenue"] == "300.00"
    assert body["last_7_days"]["businesses_with_sales"] == 1
    assert body["last_30_days"]["days"] == 30
    assert body["timezone"] == "Africa/Nairobi"
    # Signups: 30 zero-filled days ending today (business time), today counts both.
    days = body["signups_by_day"]
    assert (
        len(days) == 30 and days[-1]["businesses"] == 2 and sum(d["businesses"] for d in days) == 2
    )
    # Per-business rows: names and counts, never phones, owner names or money.
    rows = {row["name"]: row for row in body["businesses"]}
    assert set(rows) == {"Operator Duka", "Beta Duka"}
    beta = rows["Beta Duka"]
    assert beta["products"] == 1 and beta["sales"] == 1 and beta["last_sale_at"] is not None
    assert beta["business_type"] == "GENERAL_SHOP" and beta["is_active"] is True
    forbidden_keys = {"phone", "owner", "owner_phone", "revenue", "balance", "email"}
    assert not any(forbidden_keys & set(row) for row in body["businesses"])


async def test_non_admins_get_404_and_anonymous_401(
    api_factory: ApiFactory, db_session: AsyncSession
) -> None:
    admin_phone = unique_phone()
    api = await api_factory(platform_admin_phones=[admin_phone])
    owner = await _owner(api, "Beta Duka", unique_phone())
    owner_headers = bearer(str(owner["access_token"]))
    staff_phone = unique_phone()
    await add_staff(
        db_session,
        uuid.UUID(str(owner["business"]["id"])),  # type: ignore[index]
        phone=staff_phone,
        must_change_password=False,
    )
    staff_login = await login(api, staff_phone)
    staff_headers = bearer(staff_login.json()["access_token"])
    api.cookies.clear()

    owner_response = await api.get(URL, headers=owner_headers)
    assert owner_response.status_code == HTTPStatus.NOT_FOUND
    assert error_code(owner_response) == "NOT_FOUND"
    staff_response = await api.get(URL, headers=staff_headers)
    assert staff_response.status_code == HTTPStatus.NOT_FOUND
    anonymous = await api.get(URL)
    assert anonymous.status_code == HTTPStatus.UNAUTHORIZED

    # An allowlisted user who must still change their password is told so, not shown data.
    admin = await _owner(api, "Operator Duka", admin_phone)
    await db_session.execute(
        update(User).where(User.phone == admin_phone).values(must_change_password=True)
    )
    await db_session.flush()
    blocked = await api.get(URL, headers=bearer(str(admin["access_token"])))
    assert blocked.status_code == HTTPStatus.FORBIDDEN
    assert error_code(blocked) == "PASSWORD_CHANGE_REQUIRED"


async def test_without_an_allowlist_nobody_is_an_admin(api_factory: ApiFactory) -> None:
    api = await api_factory()
    owner = await _owner(api, "Beta Duka", unique_phone())
    assert owner["is_platform_admin"] is False
    me = await api.get("/api/v1/auth/me", headers=bearer(str(owner["access_token"])))
    assert me.status_code == HTTPStatus.OK and me.json()["is_platform_admin"] is False
    response = await api.get(URL, headers=bearer(str(owner["access_token"])))
    assert response.status_code == HTTPStatus.NOT_FOUND


async def test_an_allowlisted_email_also_grants_access(api_factory: ApiFactory) -> None:
    api = await api_factory(platform_admin_emails=["Ops@Example.com"])
    response = await register(
        api, business_name="Operator Duka", phone=unique_phone(), email="ops@example.com"
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    body = response.json()
    assert body["is_platform_admin"] is True
    assert (await api.get(URL, headers=bearer(body["access_token"]))).status_code == HTTPStatus.OK
    other = await _owner(api, "Beta Duka", unique_phone())
    assert other["is_platform_admin"] is False
    assert (
        await api.get(URL, headers=bearer(str(other["access_token"])))
    ).status_code == HTTPStatus.NOT_FOUND


async def test_me_and_login_report_the_flag_for_an_allowlisted_phone(
    api_factory: ApiFactory,
) -> None:
    admin_phone = unique_phone()
    api = await api_factory(platform_admin_phones=[admin_phone])
    admin = await _owner(api, "Operator Duka", admin_phone)
    me = await api.get("/api/v1/auth/me", headers=bearer(str(admin["access_token"])))
    assert me.json()["is_platform_admin"] is True
    fresh = await login(api, admin_phone, PASSWORD)
    assert fresh.status_code == HTTPStatus.OK and fresh.json()["is_platform_admin"] is True
