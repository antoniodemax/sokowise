"""GET/PATCH /api/v1/business (PRD FR-A3, §16) and the audit rows they write."""

import uuid
from http import HTTPStatus

import pytest
from app.models import AuditLog, Business
from app.services import audit as audit_service
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import error_code, set_business_active
from tests.db.isolation import Tenant

pytestmark = [pytest.mark.db, pytest.mark.anyio]

URL = "/api/v1/business"


async def _audit_rows(session: AsyncSession, business_id: str) -> list[AuditLog]:
    result = await session.scalars(
        select(AuditLog)
        .where(AuditLog.business_id == uuid.UUID(business_id))
        .order_by(AuditLog.created_at, AuditLog.id)
        .execution_options(populate_existing=True)
    )
    return list(result)


async def test_owner_reads_the_business_with_default_settings(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    response = await api.get(URL, headers=a.owner)
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert body["id"] == a.business_id
    assert body["name"] == "Alpha Duka"
    assert body["settings"] == {
        "staff_can_restock": False,
        "sale_backdate_days": 7,
        "low_stock_default_threshold": 5,
    }
    assert set(body) == {
        "id",
        "name",
        "business_type",
        "phone",
        "address",
        "currency",
        "timezone",
        "settings",
        "is_active",
        "created_at",
    }


async def test_staff_cannot_view_or_edit_business_settings(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    read = await api.get(URL, headers=a.staff)
    assert read.status_code == HTTPStatus.FORBIDDEN
    assert error_code(read) == "FORBIDDEN"
    write = await api.patch(URL, headers=a.staff, json={"name": "Hijacked"})
    assert write.status_code == HTTPStatus.FORBIDDEN
    assert error_code(write) == "FORBIDDEN"
    # Nothing leaked and nothing changed.
    assert "Alpha" not in read.text
    assert (await api.get(URL, headers=a.owner)).json()["name"] == "Alpha Duka"


async def test_unauthenticated_is_401(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    assert (await api.get(URL)).status_code == HTTPStatus.UNAUTHORIZED
    assert (await api.patch(URL, json={"name": "x"})).status_code == HTTPStatus.UNAUTHORIZED


async def test_owner_updates_profile_and_settings_with_an_audit_row(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    response = await api.patch(
        URL,
        headers=a.owner,
        json={
            "name": "Alpha Supermarket",
            "business_type": "BOUTIQUE",
            "phone": "0722 000 111",
            "timezone": "Africa/Kampala",
            "settings": {"staff_can_restock": True, "sale_backdate_days": 3},
        },
    )
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert body["name"] == "Alpha Supermarket"
    assert body["business_type"] == "BOUTIQUE"
    assert body["phone"] == "+254722000111"
    assert body["timezone"] == "Africa/Kampala"
    assert body["settings"] == {
        "staff_can_restock": True,
        "sale_backdate_days": 3,
        "low_stock_default_threshold": 5,
    }

    business = await db_session.get(Business, uuid.UUID(a.business_id))
    assert business is not None
    await db_session.refresh(business)
    assert business.settings == {
        "staff_can_restock": True,
        "sale_backdate_days": 3,
        "low_stock_default_threshold": 5,
    }

    rows = await _audit_rows(db_session, a.business_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "business.update"
    assert row.entity_type == "business"
    assert row.entity_id == uuid.UUID(a.business_id)
    assert row.actor_user_id == uuid.UUID(a.owner_user_id)
    assert row.before == {
        "name": "Alpha Duka",
        "business_type": "GENERAL_SHOP",
        "phone": None,
        "timezone": "Africa/Nairobi",
        "settings": {},
    }
    assert row.after == {
        "name": "Alpha Supermarket",
        "business_type": "BOUTIQUE",
        "phone": "+254722000111",
        "timezone": "Africa/Kampala",
        "settings": {
            "staff_can_restock": True,
            "sale_backdate_days": 3,
            "low_stock_default_threshold": 5,
        },
    }
    assert row.ip is not None


async def test_patch_with_no_effective_change_writes_no_audit_row(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    response = await api.patch(URL, headers=a.owner, json={"name": "Alpha Duka"})
    assert response.status_code == HTTPStatus.OK
    assert await _audit_rows(db_session, a.business_id) == []


@pytest.mark.parametrize(
    "payload",
    [
        {"name": ""},
        {"name": "x" * 121},
        {"business_type": "BANK"},
        {"phone": "12"},
        {"timezone": "Mars/Olympus"},
        {"settings": {"sale_backdate_days": -1}},
        {"settings": {"sale_backdate_days": 365}},
        {"settings": {"ai_daily_message_limit": 9999}},  # quotas are not owner-editable
        {"currency": "USD"},  # not editable in MVP
        {"is_active": False},  # lifecycle is not a profile field
        {"id": str(uuid.uuid4())},
        {},
    ],
)
async def test_invalid_updates_are_422_and_change_nothing(
    api: AsyncClient,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    payload: dict[str, object],
) -> None:
    a, _ = tenants
    response = await api.patch(URL, headers=a.owner, json=payload)
    if payload == {}:
        # An empty patch is valid and a no-op.
        assert response.status_code == HTTPStatus.OK
    else:
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
        assert error_code(response) == "VALIDATION_ERROR"
    assert (await api.get(URL, headers=a.owner)).json()["name"] == "Alpha Duka"
    assert await _audit_rows(db_session, a.business_id) == []


async def test_inactive_business_rejects_business_endpoints(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    await set_business_active(db_session, uuid.UUID(a.business_id), False)
    for call in (
        api.get(URL, headers=a.owner),
        api.patch(URL, headers=a.owner, json={"name": "x"}),
    ):
        response = await call
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert error_code(response) == "BUSINESS_INACTIVE"


async def test_each_tenant_sees_only_its_own_business(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    assert (await api.get(URL, headers=a.owner)).json()["id"] == a.business_id
    assert (await api.get(URL, headers=b.owner)).json()["id"] == b.business_id
    # A body or query naming the other business changes nothing.
    response = await api.patch(
        URL, headers=a.owner, params={"business_id": b.business_id}, json={"name": "A renamed"}
    )
    assert response.status_code == HTTPStatus.OK and response.json()["id"] == a.business_id
    assert (await api.get(URL, headers=b.owner)).json()["name"] == "Beta Duka"


async def test_audit_row_rolls_back_with_the_change_it_describes(
    api: AsyncClient,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If anything fails after the audit row is added, neither the change nor the row lands."""
    a, _ = tenants
    real_record = audit_service.record

    async def record_then_fail(*args: object, **kwargs: object) -> object:
        await real_record(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("simulated failure after the audit write")

    monkeypatch.setattr("app.services.business.audit.record", record_then_fail)
    response = await api.patch(URL, headers=a.owner, json={"name": "Never Persisted"})
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert "simulated" not in response.text

    assert await _audit_rows(db_session, a.business_id) == []
    business = await db_session.get(Business, uuid.UUID(a.business_id))
    assert business is not None
    await db_session.refresh(business)
    assert business.name == "Alpha Duka"
