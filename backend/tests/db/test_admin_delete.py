"""Platform admin deletes a whole business account (ARCHITECTURE §5.4)."""

import uuid
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest
from app.models import Business, User
from app.services.platform_admin import _TENANT_TABLES_IN_DELETE_ORDER
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import add_staff, bearer, error_code, login, register, unique_phone
from tests.db.conftest import ApiFactory
from tests.db.receipt_helpers import make_receipt_api, upload_ok
from tests.db.sales_helpers import make_customer, make_product, post_sale, sale_payload

pytestmark = [pytest.mark.db, pytest.mark.anyio]

ADMIN_URL = "/api/v1/admin/businesses"


@pytest.fixture
def storage_dir(tmp_path: Any) -> str:
    return str(tmp_path / "blobs")


async def _register(api: AsyncClient, business_name: str, phone: str) -> dict[str, Any]:
    response = await register(api, business_name=business_name, phone=phone)
    assert response.status_code == HTTPStatus.CREATED, response.text
    api.cookies.clear()
    body: dict[str, Any] = response.json()
    return body


async def _rows_for(session: AsyncSession, business_id: str) -> dict[str, int]:
    """Row count per table that has a business_id column, straight from the database."""
    tables = list(
        await session.scalars(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'business_id'"
            )
        )
    )
    counts: dict[str, int] = {}
    for table in tables:
        count = await session.scalar(
            text(f"SELECT count(*) FROM {table} WHERE business_id = :bid"),  # noqa: S608
            {"bid": business_id},
        )
        counts[table] = int(count or 0)
    return counts


async def test_deleting_a_business_removes_everything_it_owns(
    api_factory: ApiFactory, db_session: AsyncSession, storage_dir: str
) -> None:
    admin_phone = unique_phone()
    api = await make_receipt_api(
        api_factory, None, storage_dir, platform_admin_phones=[admin_phone]
    )
    admin = await _register(api, "Operator Duka", admin_phone)
    victim = await _register(api, "Gone Duka", unique_phone())
    headers = bearer(victim["access_token"])
    business_id = victim["business"]["id"]

    # Every kind of tenant data: product with stock, customer, cash and credit sales,
    # repayment, expense, M-Pesa message, a receipt image on disk, staff, audit rows.
    sugar = await make_product(api, headers, name="Sugar", price="150", cost="130")
    customer = await make_customer(api, headers, name="Mama Njeri")
    ok = await post_sale(api, headers, sale_payload([(sugar["id"], "2")], [("CASH", "300")]))
    assert ok.status_code == HTTPStatus.CREATED, ok.text
    credit = await post_sale(
        api,
        headers,
        sale_payload([(sugar["id"], "1")], [("CREDIT", "150")], customer_id=customer["id"]),
    )
    assert credit.status_code == HTTPStatus.CREATED, credit.text
    repaid = await api.post(
        f"/api/v1/customers/{customer['id']}/repayments",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        json={"amount": "50.00", "payment_method": "CASH"},
    )
    assert repaid.status_code == HTTPStatus.CREATED, repaid.text
    expense = await api.post(
        "/api/v1/expenses",
        headers=headers,
        json={"amount": "200.00", "category": "Transport", "payment_method": "CASH"},
    )
    assert expense.status_code == HTTPStatus.CREATED, expense.text
    sms = await api.post(
        "/api/v1/mpesa/messages",
        headers=headers,
        json={
            "text": "RK1TEST123 Confirmed. You have received Ksh300.00 from TEST 0722***123 "
            "on 18/9/26 at 2:30 PM. New M-PESA balance is Ksh1,000.00."
        },
    )
    assert sms.status_code == HTTPStatus.CREATED, sms.text
    receipt = await upload_ok(api, headers)
    receipt_key = await db_session.scalar(
        text("SELECT storage_key FROM receipts WHERE id = :rid"), {"rid": receipt["id"]}
    )
    assert receipt_key and list(Path(storage_dir).rglob("*")), "image should be on disk"
    staff_phone = unique_phone()
    staff_id = (await add_staff(db_session, uuid.UUID(business_id), phone=staff_phone)).id
    assert (await login(api, staff_phone)).status_code == HTTPStatus.OK
    api.cookies.clear()

    before = await _rows_for(db_session, business_id)
    assert before["sales"] == 2 and before["receipts"] == 1 and before["mpesa_messages"] == 1
    assert before["audit_logs"] > 0 and before["business_memberships"] == 2

    response = await api.delete(f"{ADMIN_URL}/{business_id}", headers=bearer(admin["access_token"]))
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert body["name"] == "Gone Duka" and body["users_deleted"] == 2
    assert body["receipt_images_deleted"] == 1

    db_session.expire_all()  # bulk deletes bypass the identity map
    after = await _rows_for(db_session, business_id)
    assert all(count == 0 for count in after.values()), after
    assert await db_session.get(Business, uuid.UUID(business_id)) is None
    assert await db_session.get(User, uuid.UUID(victim["user"]["id"])) is None
    assert await db_session.get(User, staff_id) is None
    assert not [p for p in Path(storage_dir).rglob("*") if p.is_file()], "image removed"
    # Their sessions are gone: the owner's old token no longer works.
    denied = await api.get("/api/v1/auth/me", headers=headers)
    assert denied.status_code == HTTPStatus.UNAUTHORIZED
    assert (await login(api, victim["user"]["phone"])).status_code == HTTPStatus.UNAUTHORIZED


async def test_a_user_who_also_belongs_elsewhere_keeps_their_login(
    api_factory: ApiFactory, db_session: AsyncSession, storage_dir: str
) -> None:
    admin_phone = unique_phone()
    api = await make_receipt_api(
        api_factory, None, storage_dir, platform_admin_phones=[admin_phone]
    )
    admin = await _register(api, "Operator Duka", admin_phone)
    doomed = await _register(api, "Doomed Duka", unique_phone())
    survivor = await _register(api, "Survivor Duka", unique_phone())
    # The survivor's owner is also staff at the doomed business.
    shared_user = await db_session.get(User, uuid.UUID(survivor["user"]["id"]))
    assert shared_user is not None
    shared_id = shared_user.id
    from app.models import BusinessMembership
    from app.models.enums import MembershipRole

    db_session.add(
        BusinessMembership(
            business_id=uuid.UUID(doomed["business"]["id"]),
            user_id=shared_id,
            role=MembershipRole.STAFF,
        )
    )
    await db_session.flush()

    response = await api.delete(
        f"{ADMIN_URL}/{doomed['business']['id']}", headers=bearer(admin["access_token"])
    )
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["users_deleted"] == 1  # only the doomed owner
    db_session.expire_all()
    assert await db_session.get(User, shared_id) is not None
    assert (await login(api, survivor["user"]["phone"])).status_code == HTTPStatus.OK
    memberships = list(
        await db_session.scalars(
            select(BusinessMembership).where(BusinessMembership.user_id == shared_id)
        )
    )
    assert [str(m.business_id) for m in memberships] == [survivor["business"]["id"]]


async def test_refusals(
    api_factory: ApiFactory, db_session: AsyncSession, storage_dir: str
) -> None:
    admin_phone = unique_phone()
    api = await make_receipt_api(
        api_factory, None, storage_dir, platform_admin_phones=[admin_phone]
    )
    admin = await _register(api, "Operator Duka", admin_phone)
    other = await _register(api, "Other Duka", unique_phone())
    admin_headers = bearer(admin["access_token"])

    own = await api.delete(f"{ADMIN_URL}/{admin['business']['id']}", headers=admin_headers)
    assert own.status_code == HTTPStatus.CONFLICT
    assert error_code(own) == "OWN_BUSINESS"
    assert await db_session.get(Business, uuid.UUID(admin["business"]["id"])) is not None

    unknown = await api.delete(f"{ADMIN_URL}/{uuid.uuid4()}", headers=admin_headers)
    assert unknown.status_code == HTTPStatus.NOT_FOUND

    not_admin = await api.delete(
        f"{ADMIN_URL}/{admin['business']['id']}", headers=bearer(other["access_token"])
    )
    assert not_admin.status_code == HTTPStatus.NOT_FOUND  # the route does not exist for them
    assert await db_session.get(Business, uuid.UUID(other["business"]["id"])) is not None

    anonymous = await api.delete(f"{ADMIN_URL}/{other['business']['id']}")
    assert anonymous.status_code == HTTPStatus.UNAUTHORIZED

    foreign_origin = await api.delete(
        f"{ADMIN_URL}/{other['business']['id']}",
        headers={**admin_headers, "Origin": "https://evil.example"},
    )
    assert foreign_origin.status_code == HTTPStatus.FORBIDDEN


async def test_every_tenant_table_is_in_the_delete_order(db_session: AsyncSession) -> None:
    """A new table with business_id must be added to the service's order, or this fails."""
    tables = set(
        await db_session.scalars(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'business_id'"
            )
        )
    )
    covered = {model.__tablename__ for model in _TENANT_TABLES_IN_DELETE_ORDER}
    assert tables == covered, tables ^ covered
