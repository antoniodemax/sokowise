"""/api/v1/customers (ROADMAP Phase 6; PRD FR-G1, §16; DATA_MAPPING §3.8)."""

import logging
import uuid
from decimal import Decimal
from http import HTTPStatus
from typing import Any

import pytest
from app.core.logging import JsonFormatter
from app.models import AuditLog, Customer
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import error_code, set_business_active
from tests.db.isolation import Tenant

pytestmark = [pytest.mark.db, pytest.mark.anyio]

URL = "/api/v1/customers"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": "Mama Njeri"}
    payload.update(overrides)
    return payload


async def _create(api: AsyncClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    response = await api.post(URL, headers=headers, json=_payload(**overrides))
    assert response.status_code == HTTPStatus.CREATED, response.text
    body: dict[str, Any] = response.json()
    return body


# --- create -----------------------------------------------------------------------------


async def test_owner_creates_a_customer_with_defaults(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    body = await _create(api, a.owner, name="  Mama Njeri ")
    assert body["name"] == "Mama Njeri"
    assert body["phone"] is None and body["notes"] is None and body["credit_limit"] is None
    assert body["balance"] == "0.00"
    assert body["is_active"] is True
    assert set(body) == {
        "id",
        "name",
        "phone",
        "notes",
        "credit_limit",
        "balance",
        "is_active",
        "created_at",
        "updated_at",
    }
    row = await db_session.get(Customer, uuid.UUID(body["id"]))
    assert row is not None
    assert row.business_id == uuid.UUID(a.business_id)  # from the context, never the client
    assert row.balance == Decimal("0.00")


async def test_staff_can_create_and_read_customers(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    """PRD §16: "Create / edit customers" is a member permission (attendants open accounts)."""
    a, _ = tenants
    assert a.staff is not None
    body = await _create(api, a.staff, name="Staff Made", phone="0711000111")
    assert (await api.get(f"{URL}/{body['id']}", headers=a.staff)).status_code == HTTPStatus.OK
    assert (await api.get(URL, headers=a.staff)).status_code == HTTPStatus.OK
    assert (await api.get(URL, headers=a.staff, params={"q": "0711"})).json()[0]["id"] == body["id"]


async def test_phone_is_normalised_and_credit_limit_kept(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    body = await _create(
        api, a.owner, phone="0712 345 678", notes="  Buys on Fridays ", credit_limit="2500"
    )
    assert body["phone"] == "+254712345678"
    assert body["notes"] == "Buys on Fridays"
    assert body["credit_limit"] == "2500.00"


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 121},
        {"phone": "12345"},
        {"phone": "not a phone"},
        {"credit_limit": "-1"},
        {"credit_limit": "10.123"},
        {"notes": "n" * 2001},
        {"balance": "100"},  # ledger cache, never a request field
        {"is_active": False},
        {"business_id": str(uuid.uuid4())},
        {"id": str(uuid.uuid4())},
    ],
)
async def test_invalid_payloads_are_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], overrides: dict[str, Any]
) -> None:
    a, _ = tenants
    response = await api.post(URL, headers=a.owner, json=_payload(**overrides))
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, (overrides, response.text)
    assert error_code(response) == "VALIDATION_ERROR"
    assert (await api.get(URL, headers=a.owner)).json() == []


async def test_missing_name_is_422(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    response = await api.post(URL, headers=a.owner, json={"phone": "0712345678"})
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


async def test_phone_is_unique_per_business_but_not_across_businesses(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    first = await _create(api, a.owner, name="Amina", phone="+254712345678")
    dup = await api.post(URL, headers=a.owner, json=_payload(name="Amina K", phone="0712345678"))
    assert dup.status_code == HTTPStatus.CONFLICT
    assert error_code(dup) == "CUSTOMER_PHONE_EXISTS"
    assert "uq_customers" not in dup.text and "asyncpg" not in dup.text
    other = await _create(api, b.owner, name="Amina", phone="0712345678")
    assert other["id"] != first["id"]
    # Two customers without a phone are fine; the same name is fine too.
    await _create(api, a.owner, name="Walk-in")
    await _create(api, a.owner, name="Walk-in")
    assert len((await api.get(URL, headers=a.owner)).json()) == 3


async def test_blank_phone_means_no_phone(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    assert (await _create(api, a.owner, phone=""))["phone"] is None
    assert (await _create(api, a.owner, phone=None))["phone"] is None


# --- read / list ----------------------------------------------------------------------


async def test_get_and_unknown_customer(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    body = await _create(api, a.owner)
    one = await api.get(f"{URL}/{body['id']}", headers=a.owner)
    assert one.status_code == HTTPStatus.OK and one.json() == body
    missing = await api.get(f"{URL}/{uuid.uuid4()}", headers=a.owner)
    assert missing.status_code == HTTPStatus.NOT_FOUND and error_code(missing) == "NOT_FOUND"
    assert (await api.get(f"{URL}/not-a-uuid", headers=a.owner)).status_code == (
        HTTPStatus.UNPROCESSABLE_ENTITY
    )


async def test_list_is_tenant_scoped_ordered_and_limited(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    await _create(api, a.owner, name="zawadi")
    await _create(api, a.owner, name="Amina")
    await _create(api, a.owner, name="Brian")
    foreign = await _create(api, b.owner, name="Amina")
    listed = await api.get(URL, headers=a.owner)
    assert listed.status_code == HTTPStatus.OK
    assert [c["name"] for c in listed.json()] == ["Amina", "Brian", "zawadi"]  # case-insensitive
    assert foreign["id"] not in listed.text
    assert [c["id"] for c in (await api.get(URL, headers=b.owner)).json()] == [foreign["id"]]
    assert len((await api.get(URL, headers=a.owner, params={"limit": 2})).json()) == 2
    assert (await api.get(URL, headers=a.owner, params={"limit": 0})).status_code == 422
    assert (await api.get(URL, headers=a.owner, params={"limit": 501})).status_code == 422


async def test_archived_customers_are_hidden_by_default(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """Archive is Phase 7, but the list semantics (BR-12) are fixed now."""
    a, _ = tenants
    body = await _create(api, a.owner, name="Old Customer")
    row = await db_session.get(Customer, uuid.UUID(body["id"]))
    assert row is not None
    row.is_active = False
    await db_session.flush()
    assert (await api.get(URL, headers=a.owner)).json() == []
    everything = (await api.get(URL, headers=a.owner, params={"include_archived": "true"})).json()
    assert [c["id"] for c in everything] == [body["id"]]
    assert (await api.get(f"{URL}/{body['id']}", headers=a.owner)).status_code == HTTPStatus.OK


# --- search -------------------------------------------------------------------------


async def test_search_by_name_is_a_case_insensitive_substring(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    await _create(api, a.owner, name="Mama Njeri")
    await _create(api, a.owner, name="Njeri Wanjiku")
    await _create(api, a.owner, name="Brian O.")
    await _create(api, b.owner, name="Njeri Foreign")
    found = (await api.get(URL, headers=a.owner, params={"q": "NJERI"})).json()
    assert [c["name"] for c in found] == ["Mama Njeri", "Njeri Wanjiku"]
    assert (await api.get(URL, headers=a.owner, params={"q": "o."})).json()[0]["name"] == "Brian O."
    assert (await api.get(URL, headers=a.owner, params={"q": "zzz"})).json() == []
    # LIKE wildcards are literal.
    assert (await api.get(URL, headers=a.owner, params={"q": "%"})).json() == []
    assert (await api.get(URL, headers=a.owner, params={"q": "_"})).json() == []


@pytest.mark.parametrize(
    "query", ["+254712345678", "0712345678", "0712", "254712", "+254 712", "0712-345", "712345678"]
)
async def test_search_by_phone_accepts_local_and_partial_forms(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], query: str
) -> None:
    a, b = tenants
    target = await _create(api, a.owner, name="Amina", phone="0712345678")
    await _create(api, a.owner, name="Other", phone="0722000000")
    await _create(api, b.owner, name="Foreign", phone="0712345678")
    found = (await api.get(URL, headers=a.owner, params={"q": query})).json()
    assert [c["id"] for c in found] == [target["id"]], query


async def test_search_by_phone_never_crosses_tenants(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    foreign = await _create(api, b.owner, name="Foreign", phone="0733111222")
    assert (await api.get(URL, headers=a.owner, params={"q": "0733111222"})).json() == []
    assert (await api.get(URL, headers=a.owner, params={"q": "Foreign"})).json() == []
    assert [
        c["id"] for c in (await api.get(URL, headers=b.owner, params={"q": "0733"})).json()
    ] == [foreign["id"]]


async def test_blank_query_lists_everyone(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    await _create(api, a.owner, name="One")
    await _create(api, a.owner, name="Two")
    for q in ("", "   "):
        assert len((await api.get(URL, headers=a.owner, params={"q": q})).json()) == 2
    assert (await api.get(URL, headers=a.owner, params={"q": "x" * 121})).status_code == 422


# --- authorization / lifecycle ---------------------------------------------------------


async def test_unauthenticated_is_401(api: AsyncClient) -> None:
    assert (await api.get(URL)).status_code == HTTPStatus.UNAUTHORIZED
    assert (await api.post(URL, json=_payload())).status_code == HTTPStatus.UNAUTHORIZED
    assert (await api.get(f"{URL}/{uuid.uuid4()}")).status_code == HTTPStatus.UNAUTHORIZED


async def test_inactive_business_is_403(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    body = await _create(api, a.owner)
    await set_business_active(db_session, uuid.UUID(a.business_id), False)
    for call in (
        api.get(URL, headers=a.owner),
        api.get(f"{URL}/{body['id']}", headers=a.owner),
        api.post(URL, headers=a.owner, json=_payload(name="Blocked")),
    ):
        response = await call
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert error_code(response) == "BUSINESS_INACTIVE"


async def test_cross_tenant_customer_is_indistinguishable_from_missing(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    foreign = await _create(api, b.owner, name="Beta Customer", phone="0700000001")
    denied = await api.get(f"{URL}/{foreign['id']}", headers=a.owner)
    missing = await api.get(f"{URL}/{uuid.uuid4()}", headers=a.owner)
    assert denied.status_code == missing.status_code == HTTPStatus.NOT_FOUND
    assert denied.json()["error"]["message"] == missing.json()["error"]["message"]
    assert "Beta" not in denied.text and "0700000001" not in denied.text


# --- privacy ----------------------------------------------------------------------------


async def test_customer_pii_stays_out_of_logs_and_audit(
    api: AsyncClient,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    caplog: pytest.LogCaptureFixture,
) -> None:
    a, _ = tenants
    logging.getLogger().addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG)
    await _create(api, a.owner, name="Private Person", phone="0799888777", notes="owes for sugar")
    dup = await api.post(URL, headers=a.owner, json=_payload(name="Again", phone="0799888777"))
    assert dup.status_code == HTTPStatus.CONFLICT
    rendered = "\n".join(JsonFormatter().format(r) for r in caplog.records)
    for secret in ("Private Person", "+254799888777", "0799888777", "owes for sugar"):
        assert secret not in rendered
        assert secret not in dup.text
    # Customer creation is not an audited action (PRD FR-K1; DATA_MAPPING §5).
    rows = (await db_session.scalars(select(AuditLog))).all()
    assert rows == []
