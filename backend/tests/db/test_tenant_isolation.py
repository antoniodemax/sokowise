"""Every tenant-scoped endpoint, run through the isolation helper (ROADMAP Phase 4).

To register a new resource type, add an `IsolationCase` to `CASES`. Phase 4 has one
tenant-scoped resource: business members (`/api/v1/users/{user_id}`).
"""

from http import HTTPStatus

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import OTHER_PASSWORD, PASSWORD, unique_phone
from tests.db.isolation import IsolationCase, Tenant, assert_tenant_isolated

pytestmark = [pytest.mark.db, pytest.mark.anyio]

USERS_URL = "/api/v1/users"


async def _create_staff_member(api: AsyncClient, session: AsyncSession, tenant: Tenant) -> str:
    response = await api.post(
        USERS_URL,
        headers=tenant.owner,
        json={"full_name": "Isolated Staff", "phone": unique_phone(), "password": PASSWORD},
    )
    assert response.status_code == HTTPStatus.CREATED, response.text
    user_id: str = response.json()["user_id"]
    return user_id


CASES: list[IsolationCase] = [
    IsolationCase(
        name="users",
        create_in=_create_staff_member,
        read_url=lambda user_id: f"{USERS_URL}/{user_id}",
        list_url=USERS_URL,
        mutations=(
            ("PATCH", lambda user_id: f"{USERS_URL}/{user_id}", {"role": "OWNER"}),
            ("PATCH", lambda user_id: f"{USERS_URL}/{user_id}", {"is_active": False}),
            (
                "POST",
                lambda user_id: f"{USERS_URL}/{user_id}/reset-password",
                {"password": OTHER_PASSWORD},
            ),
        ),
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
async def test_tenant_isolation(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant], case: IsolationCase
) -> None:
    a, b = tenants
    await assert_tenant_isolated(api, db_session, case, a, b)
    # And in the other direction, so the check is not accidentally one-sided.
    await assert_tenant_isolated(api, db_session, case, b, a)
