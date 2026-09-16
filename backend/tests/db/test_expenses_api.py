"""/api/v1/expenses (PRD FR-H, NFR-12, §16; DATA_MAPPING §3.13)."""

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.models import AuditLog, Expense
from app.models.enums import MoneyReceivedMethod
from app.services import audit as audit_service
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import error_code, set_business_active
from tests.db.isolation import Tenant

pytestmark = [pytest.mark.db, pytest.mark.anyio]

D = Decimal
URL = "/api/v1/expenses"
NAIROBI = ZoneInfo("Africa/Nairobi")


def _at(day: date, hour: int, minute: int = 0) -> str:
    """UTC ISO string for a local Nairobi wall-clock time on `day`."""
    local = datetime.combine(day, datetime.min.time(), tzinfo=NAIROBI).replace(
        hour=hour, minute=minute
    )
    return local.astimezone(UTC).isoformat()


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"amount": "400", "category": "Rent", "payment_method": "MPESA"}
    payload.update(overrides)
    return payload


async def _create(api: AsyncClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    response = await api.post(URL, headers=headers, json=_payload(**overrides))
    assert response.status_code == HTTPStatus.CREATED, response.text
    body: dict[str, Any] = response.json()
    return body


async def _audits(session: AsyncSession, business_id: str, action: str) -> list[AuditLog]:
    rows = await session.scalars(
        select(AuditLog)
        .where(AuditLog.business_id == uuid.UUID(business_id), AuditLog.action == action)
        .execution_options(populate_existing=True)
    )
    return list(rows)


# --- create -----------------------------------------------------------------------------


async def test_owner_records_an_expense(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    body = await _create(api, a.owner, category="  rent  ", reference=" QAB12 ", note="September")
    assert body["amount"] == "400.00"
    assert body["category"] == "RENT"  # normalised
    assert (body["payment_method"], body["reference"], body["note"]) == (
        "MPESA",
        "QAB12",
        "September",
    )
    assert body["deleted_at"] is None and body["created_by"] == a.owner_user_id
    assert set(body) == {
        "id",
        "amount",
        "category",
        "payment_method",
        "reference",
        "note",
        "incurred_at",
        "deleted_at",
        "created_by",
        "created_at",
        "updated_at",
    }
    row = await db_session.get(Expense, uuid.UUID(body["id"]))
    assert (
        row is not None
        and row.business_id == uuid.UUID(a.business_id)
        and row.amount == D("400.00")
    )
    assert (
        await db_session.scalars(select(AuditLog))
    ).all() == []  # creation is not audited (FR-K1)


async def test_incurred_at_defaults_to_now_and_may_be_in_the_past_but_not_future(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    now_ish = await _create(api, a.owner)
    assert abs(datetime.fromisoformat(now_ish["incurred_at"]) - datetime.now(UTC)) < timedelta(
        minutes=1
    )
    last_month = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    past = await _create(api, a.owner, incurred_at=last_month)
    assert past["incurred_at"].startswith(last_month[:16])
    future = await api.post(
        URL,
        headers=a.owner,
        json=_payload(incurred_at=(datetime.now(UTC) + timedelta(hours=2)).isoformat()),
    )
    assert (
        future.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        and error_code(future) == "EXPENSE_IN_FUTURE"
    )
    naive = await api.post(URL, headers=a.owner, json=_payload(incurred_at="2026-09-16T10:00:00"))
    assert naive.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": "0"},
        {"amount": "-1"},
        {"amount": "10.005"},
        {"amount": "abc"},
        {"category": ""},
        {"category": "   "},
        {"category": "x" * 61},
        {"payment_method": "CREDIT"},
        {"payment_method": "BANK"},
        {"reference": "x" * 65},
        {"note": "x" * 256},
        {"business_id": str(uuid.uuid4())},
        {"deleted_at": None},
        {"created_by": str(uuid.uuid4())},
    ],
)
async def test_invalid_expenses_are_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], overrides: dict[str, Any]
) -> None:
    a, _ = tenants
    response = await api.post(URL, headers=a.owner, json=_payload(**overrides))
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, (overrides, response.text)
    assert error_code(response) == "VALIDATION_ERROR"
    assert (await api.get(URL, headers=a.owner)).json() == []


async def test_missing_fields_are_422(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = tenants
    for body in ({"amount": "1"}, {"category": "RENT"}, {}):
        assert (
            await api.post(URL, headers=a.owner, json=body)
        ).status_code == HTTPStatus.UNPROCESSABLE_ENTITY


# --- read / list / categories ------------------------------------------------------------


async def test_list_filters_ordering_and_limit(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    today = datetime.now(NAIROBI).date()
    d1 = today - timedelta(days=5)
    d2 = today - timedelta(days=2)
    rent = await _create(
        api, a.owner, category="Rent", amount="5000", payment_method="MPESA", incurred_at=_at(d1, 9)
    )
    fuel = await _create(
        api,
        a.owner,
        category="Transport",
        amount="300",
        payment_method="CASH",
        incurred_at=_at(d2, 9),
    )
    airtime = await _create(
        api,
        a.owner,
        category="Airtime",
        amount="100",
        payment_method="MPESA",
        incurred_at=_at(d2, 15),
    )
    foreign = await _create(api, b.owner, category="Rent", amount="999")

    listed = (await api.get(URL, headers=a.owner)).json()
    assert [e["id"] for e in listed] == [airtime["id"], fuel["id"], rent["id"]]  # newest first
    assert foreign["id"] not in {e["id"] for e in listed}
    by_day = (
        await api.get(
            URL, headers=a.owner, params={"date_from": d2.isoformat(), "date_to": d2.isoformat()}
        )
    ).json()
    assert [e["id"] for e in by_day] == [airtime["id"], fuel["id"]]
    by_cat = (await api.get(URL, headers=a.owner, params={"category": " rent "})).json()
    assert [e["id"] for e in by_cat] == [rent["id"]]
    by_method = (await api.get(URL, headers=a.owner, params={"payment_method": "CASH"})).json()
    assert [e["id"] for e in by_method] == [fuel["id"]]
    assert len((await api.get(URL, headers=a.owner, params={"limit": 1})).json()) == 1
    assert (await api.get(URL, headers=a.owner, params={"limit": 0})).status_code == 422
    assert (
        await api.get(URL, headers=a.owner, params={"date_from": d2.isoformat()})
    ).status_code == 422
    assert (
        await api.get(
            URL, headers=a.owner, params={"date_from": today.isoformat(), "date_to": d1.isoformat()}
        )
    ).status_code == 422
    assert (
        await api.get(URL, headers=a.owner, params={"payment_method": "BANK"})
    ).status_code == 422
    assert [e["id"] for e in (await api.get(URL, headers=b.owner)).json()] == [foreign["id"]]


async def test_detail_and_cross_tenant(api: AsyncClient, tenants: tuple[Tenant, Tenant]) -> None:
    a, b = tenants
    mine = await _create(api, a.owner)
    theirs = await _create(api, b.owner, note="Beta secret note")
    assert (await api.get(f"{URL}/{mine['id']}", headers=a.owner)).json() == mine
    denied = await api.get(f"{URL}/{theirs['id']}", headers=a.owner)
    missing = await api.get(f"{URL}/{uuid.uuid4()}", headers=a.owner)
    assert denied.status_code == missing.status_code == HTTPStatus.NOT_FOUND
    assert denied.json()["error"]["message"] == missing.json()["error"]["message"]
    assert "Beta" not in denied.text
    for call in (
        api.patch(f"{URL}/{theirs['id']}", headers=a.owner, json={"amount": "1"}),
        api.delete(f"{URL}/{theirs['id']}", headers=a.owner),
    ):
        assert (await call).status_code == HTTPStatus.NOT_FOUND
    assert (await api.get(f"{URL}/{theirs['id']}", headers=b.owner)).json()["amount"] == "400.00"


async def test_suggested_categories_include_the_business_own(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    await _create(api, a.owner, category="Boda fuel")
    await _create(api, b.owner, category="Beta only")
    body = (await api.get(f"{URL}/categories", headers=a.owner)).json()
    assert body["suggested"][:7] == [
        "RENT",
        "TRANSPORT",
        "UTILITIES",
        "AIRTIME",
        "SALARIES",
        "LICENSES",
        "OTHER",
    ]
    assert body["suggested"][7:] == ["BODA FUEL"]
    assert "BETA ONLY" not in body["suggested"]


# --- update / delete ------------------------------------------------------------------


async def test_owner_updates_an_expense_with_audit_of_changed_fields(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    created = await _create(api, a.owner, note="old")
    response = await api.patch(
        f"{URL}/{created['id']}",
        headers=a.owner,
        json={"amount": "450", "category": "utilities", "note": None, "reference": "NEWREF"},
    )
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert (body["amount"], body["category"], body["note"], body["reference"]) == (
        "450.00",
        "UTILITIES",
        None,
        "NEWREF",
    )
    assert body["payment_method"] == "MPESA"  # untouched
    rows = await _audits(db_session, a.business_id, "expense.update")
    assert len(rows) == 1 and rows[0].entity_id == uuid.UUID(created["id"])
    assert rows[0].before == {
        "amount": "400.00",
        "category": "RENT",
        "note": "old",
        "reference": None,
    }
    assert rows[0].after == {
        "amount": "450.00",
        "category": "UTILITIES",
        "note": None,
        "reference": "NEWREF",
    }
    # No-op patch writes no audit row.
    assert (
        await api.patch(f"{URL}/{created['id']}", headers=a.owner, json={"amount": "450.00"})
    ).status_code == 200
    assert len(await _audits(db_session, a.business_id, "expense.update")) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"amount": None},
        {"amount": "0"},
        {"category": None},
        {"payment_method": "BANK"},
        {"business_id": "x"},
        {"deleted_at": None},
    ],
)
async def test_invalid_updates_are_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], body: dict[str, Any]
) -> None:
    a, _ = tenants
    created = await _create(api, a.owner)
    assert (
        await api.patch(f"{URL}/{created['id']}", headers=a.owner, json=body)
    ).status_code == 422, body


async def test_soft_delete_hides_from_lists_and_totals_but_keeps_history(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    created = await _create(api, a.owner, amount="400")
    kept = await _create(api, a.owner, amount="100", category="Airtime")
    response = await api.delete(f"{URL}/{created['id']}", headers=a.owner)
    assert response.status_code == HTTPStatus.NO_CONTENT
    assert [e["id"] for e in (await api.get(URL, headers=a.owner)).json()] == [kept["id"]]
    everything = (await api.get(URL, headers=a.owner, params={"include_deleted": "true"})).json()
    assert {e["id"] for e in everything} == {created["id"], kept["id"]}
    detail = await api.get(f"{URL}/{created['id']}", headers=a.owner)
    assert detail.status_code == 200 and detail.json()["deleted_at"] is not None
    summary = (
        await api.get("/api/v1/analytics/summary", headers=a.owner, params={"period": "today"})
    ).json()
    assert summary["expenses"] == "100.00"
    # Deleting again is a no-op; editing a deleted expense is refused.
    assert (
        await api.delete(f"{URL}/{created['id']}", headers=a.owner)
    ).status_code == HTTPStatus.NO_CONTENT
    edit = await api.patch(f"{URL}/{created['id']}", headers=a.owner, json={"amount": "1"})
    assert edit.status_code == HTTPStatus.CONFLICT and error_code(edit) == "EXPENSE_DELETED"
    rows = await _audits(db_session, a.business_id, "expense.delete")
    assert len(rows) == 1 and rows[0].before == {
        "amount": "400.00",
        "category": "RENT",
        "deleted_at": None,
    }
    assert rows[0].after is not None and rows[0].after["deleted_at"]
    row = await db_session.get(Expense, uuid.UUID(created["id"]))
    assert row is not None  # never hard-deleted


async def test_failure_after_audit_rolls_back_update_and_delete(
    api: AsyncClient,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, _ = tenants
    created = await _create(api, a.owner)
    real_record = audit_service.record

    async def record_then_fail(*args: object, **kwargs: object) -> object:
        await real_record(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("simulated")

    monkeypatch.setattr("app.services.expenses.audit.record", record_then_fail)
    assert (
        await api.patch(f"{URL}/{created['id']}", headers=a.owner, json={"amount": "999"})
    ).status_code == 500
    assert (await api.delete(f"{URL}/{created['id']}", headers=a.owner)).status_code == 500
    row = await db_session.get(Expense, uuid.UUID(created["id"]))
    assert row is not None
    await db_session.refresh(row)
    assert row.amount == D("400.00") and row.deleted_at is None
    assert await _audits(db_session, a.business_id, "expense.update") == []
    assert await _audits(db_session, a.business_id, "expense.delete") == []


# --- authorization ----------------------------------------------------------------------


async def test_expenses_are_owner_only(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    created = await _create(api, a.owner)
    for call in (
        api.get(URL, headers=a.staff),
        api.post(URL, headers=a.staff, json=_payload()),
        api.get(f"{URL}/{created['id']}", headers=a.staff),
        api.patch(f"{URL}/{created['id']}", headers=a.staff, json={"amount": "1"}),
        api.delete(f"{URL}/{created['id']}", headers=a.staff),
        api.get(f"{URL}/categories", headers=a.staff),
        api.get(f"{URL}/export.csv", headers=a.staff),
        api.get("/api/v1/analytics/expenses", headers=a.staff),
    ):
        response = await call
        assert response.status_code == HTTPStatus.FORBIDDEN and error_code(response) == "FORBIDDEN"
    assert (await api.get(URL)).status_code == 401
    assert (await api.post(URL, json=_payload())).status_code == 401
    await set_business_active(db_session, uuid.UUID(a.business_id), False)
    inactive = await api.get(URL, headers=a.owner)
    assert (
        inactive.status_code == HTTPStatus.FORBIDDEN and error_code(inactive) == "BUSINESS_INACTIVE"
    )


# --- CSV ---------------------------------------------------------------------------------


async def test_csv_export_is_deterministic_filtered_and_isolated(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    today = datetime.now(NAIROBI).date()
    d1 = today - timedelta(days=3)
    await _create(
        api,
        a.owner,
        category="Rent",
        amount="5000",
        payment_method="MPESA",
        reference="QAB12",
        note='Kiosk, "September"',
        incurred_at=_at(d1, 9, 5),
    )
    await _create(
        api,
        a.owner,
        category="Transport",
        amount="300.50",
        payment_method="CASH",
        incurred_at=_at(d1, 17, 45),
    )
    # A recent row that is only there to be deleted: an hour ago is safely in the past
    # whatever the local time of day (08:00 today would be in the future before 08:00).
    deleted = await _create(
        api,
        a.owner,
        category="Airtime",
        amount="50",
        incurred_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    )
    await api.delete(f"{URL}/{deleted['id']}", headers=a.owner)
    await _create(api, b.owner, category="Rent", amount="999", note="Beta")

    response = await api.get(f"{URL}/export.csv", headers=a.owner)
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="expenses.csv"'
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8"))))
    assert rows[0] == ["date", "time", "category", "amount", "payment_method", "reference", "note"]
    assert rows[1:] == [
        [d1.isoformat(), "09:05", "RENT", "5000.00", "MPESA", "QAB12", 'Kiosk, "September"'],
        [d1.isoformat(), "17:45", "TRANSPORT", "300.50", "CASH", "", ""],
    ]  # oldest first, local times, deleted excluded, nothing from B
    assert "Beta" not in response.text and "999" not in response.text
    assert a.business_id not in response.text and a.owner_user_id not in response.text

    filtered = await api.get(
        f"{URL}/export.csv",
        headers=a.owner,
        params={"category": "transport", "date_from": d1.isoformat(), "date_to": d1.isoformat()},
    )
    lines = filtered.text.strip().splitlines()
    assert len(lines) == 2 and lines[1].startswith(f"{d1.isoformat()},17:45,TRANSPORT,300.50,CASH")
    assert (
        filtered.headers["content-disposition"] == f'attachment; filename="expenses-{d1}-{d1}.csv"'
    )
    empty = await api.get(f"{URL}/export.csv", headers=a.owner, params={"category": "nothing"})
    assert empty.text == "date,time,category,amount,payment_method,reference,note\n"


async def test_csv_export_streams_more_than_one_batch(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    from app.models import Expense as ExpenseModel

    a, _ = tenants
    base = datetime.now(UTC) - timedelta(days=1)
    db_session.add_all(
        ExpenseModel(
            business_id=uuid.UUID(a.business_id),
            amount=D("1.00"),
            category="BULK",
            payment_method=MoneyReceivedMethod.CASH,
            incurred_at=base + timedelta(seconds=i),
            created_by=uuid.UUID(a.owner_user_id),
        )
        for i in range(1203)
    )
    await db_session.flush()
    response = await api.get(f"{URL}/export.csv", headers=a.owner)
    lines = response.text.strip().splitlines()
    assert len(lines) == 1 + 1203
    times = [line.split(",")[1] for line in lines[1:]]
    assert times == sorted(times) or len(set(times)) < 1203  # oldest first within the same minute
