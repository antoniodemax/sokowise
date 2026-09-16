"""Customer credit ledger: balance, repayments, adjustments, ledger, debtors, limits
(ROADMAP Phase 7; PRD FR-G2-G5, BR-7; DATA_MAPPING §3.12)."""

import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from http import HTTPStatus

import pytest
from app.core.logging import JsonFormatter
from app.models import AuditLog, CreditTransaction, Customer
from app.models.enums import MembershipRole
from app.services import audit as audit_service
from app.services import credit as credit_service
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import error_code, set_business_active
from tests.db.credit_helpers import (
    CUSTOMERS_URL,
    DEBTORS_URL,
    adjust,
    charge,
    create_customer,
    db_balance,
    repay,
)
from tests.db.isolation import Tenant

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def _audits(session: AsyncSession, business_id: str, action: str) -> list[AuditLog]:
    rows = await session.scalars(
        select(AuditLog)
        .where(AuditLog.business_id == uuid.UUID(business_id), AuditLog.action == action)
        .execution_options(populate_existing=True)
    )
    return list(rows)


# --- the accounting trace from the phase brief (executed, not calculated) -----------------


async def test_accounting_trace(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    customer = await create_customer(api, a.owner)
    cid = customer["id"]
    assert customer["balance"] == "0.00"

    await charge(db_session, a, cid, "5000")
    assert await db_balance(db_session, cid) == (Decimal("5000.00"), Decimal("5000.00"))

    r1 = await repay(api, a.owner, cid, "2000", "CASH")
    assert r1.status_code == HTTPStatus.CREATED, r1.text
    assert r1.json()["balance_after"] == "3000.00"
    assert await db_balance(db_session, cid) == (Decimal("3000.00"), Decimal("3000.00"))

    adj = await adjust(api, a.owner, cid, "500", "INCREASE", reason="forgotten bread")
    assert adj.status_code == HTTPStatus.CREATED, adj.text
    assert adj.json()["balance_after"] == "3500.00"
    assert await db_balance(db_session, cid) == (Decimal("3500.00"), Decimal("3500.00"))

    r2 = await repay(api, a.owner, cid, "3500", "MPESA", reference="QGH7XYZ123")
    assert r2.status_code == HTTPStatus.CREATED, r2.text
    assert r2.json()["balance_after"] == "0.00"
    assert r2.json()["reference"] == "QGH7XYZ123"
    assert await db_balance(db_session, cid) == (Decimal("0.00"), Decimal("0.00"))

    over = await repay(api, a.owner, cid, "1", "CASH")
    assert over.status_code == HTTPStatus.CONFLICT
    assert error_code(over) == "REPAYMENT_EXCEEDS_BALANCE"
    assert await db_balance(db_session, cid) == (Decimal("0.00"), Decimal("0.00"))

    ledger = await api.get(f"{CUSTOMERS_URL}/{cid}/ledger", headers=a.owner)
    assert ledger.status_code == HTTPStatus.OK
    body = ledger.json()
    assert body["balance"] == "0.00"
    assert [(e["entry_type"], e["amount"], e["balance_after"]) for e in body["entries"]] == [
        ("REPAYMENT", "-3500.00", "0.00"),
        ("ADJUSTMENT", "500.00", "3500.00"),
        ("REPAYMENT", "-2000.00", "3000.00"),
        ("CHARGE", "5000.00", "5000.00"),
    ]
    rows = (await db_session.scalars(select(CreditTransaction))).all()
    assert len(rows) == 4 and all(r.customer_id == uuid.UUID(cid) for r in rows)
    assert (await api.get(f"{CUSTOMERS_URL}/{cid}", headers=a.owner)).json()["balance"] == "0.00"


# --- balance ----------------------------------------------------------------------------


async def test_balance_is_the_ledger_sum_with_exact_decimals(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    await charge(db_session, a, cid, "0.10")
    await charge(db_session, a, cid, "0.20")
    assert (await repay(api, a.owner, cid, "0.15")).status_code == HTTPStatus.CREATED
    assert (await adjust(api, a.owner, cid, "0.05", "DECREASE")).status_code == HTTPStatus.CREATED
    assert (await adjust(api, a.owner, cid, "0.01", "INCREASE")).status_code == HTTPStatus.CREATED
    assert await db_balance(db_session, cid) == (Decimal("0.11"), Decimal("0.11"))
    assert (await api.get(f"{CUSTOMERS_URL}/{cid}", headers=a.owner)).json()["balance"] == "0.11"


# --- repayments -------------------------------------------------------------------------


async def test_partial_and_full_repayments(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    await charge(db_session, a, cid, "1000")
    partial = await repay(api, a.owner, cid, "400", "MPESA", reference="ABC123")
    assert partial.status_code == HTTPStatus.CREATED
    entry = partial.json()
    assert entry["entry_type"] == "REPAYMENT"
    assert entry["amount"] == "-400.00"
    assert entry["payment_method"] == "MPESA"
    assert entry["balance_after"] == "600.00"
    assert entry["created_by"] == a.owner_user_id
    full = await repay(api, a.owner, cid, "600.00")
    assert full.status_code == HTTPStatus.CREATED and full.json()["balance_after"] == "0.00"
    assert await db_balance(db_session, cid) == (Decimal("0.00"), Decimal("0.00"))


async def test_repayment_above_balance_is_409_and_writes_nothing(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    await charge(db_session, a, cid, "1000")
    response = await repay(api, a.owner, cid, "1000.01")
    assert response.status_code == HTTPStatus.CONFLICT
    assert error_code(response) == "REPAYMENT_EXCEEDS_BALANCE"
    assert await db_balance(db_session, cid) == (Decimal("1000.00"), Decimal("1000.00"))
    assert len((await db_session.scalars(select(CreditTransaction))).all()) == 1
    assert await _audits(db_session, a.business_id, "credit.repayment") == []


async def test_explicit_overpayment_records_credit_in_favour(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    """PRD BR-7: a balance may go negative, but only when the caller says so."""
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    await charge(db_session, a, cid, "1000")
    response = await repay(api, a.owner, cid, "1500", allow_overpayment=True)
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()["balance_after"] == "-500.00"
    assert await db_balance(db_session, cid) == (Decimal("-500.00"), Decimal("-500.00"))
    # Not a debtor any more; and a further repayment without the flag is still refused.
    assert (await api.get(DEBTORS_URL, headers=a.owner)).json() == []
    assert (await repay(api, a.owner, cid, "1")).status_code == HTTPStatus.CONFLICT


@pytest.mark.parametrize(
    "body",
    [
        {"amount": "0", "payment_method": "CASH"},
        {"amount": "-5", "payment_method": "CASH"},
        {"amount": "10.123", "payment_method": "CASH"},
        {"amount": "abc", "payment_method": "CASH"},
        {"amount": "10"},
        {"amount": "10", "payment_method": "CREDIT"},
        {"amount": "10", "payment_method": "BANK"},
        {"amount": "10", "payment_method": "CASH", "reference": "x" * 65},
        {"amount": "10", "payment_method": "CASH", "balance_after": "0"},
        {"amount": "10", "payment_method": "CASH", "customer_id": str(uuid.uuid4())},
    ],
)
async def test_invalid_repayment_payloads_are_422(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant], body: dict[str, str]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    await charge(db_session, a, cid, "100")
    response = await api.post(f"{CUSTOMERS_URL}/{cid}/repayments", headers=a.owner, json=body)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, body
    assert await db_balance(db_session, cid) == (Decimal("100.00"), Decimal("100.00"))


async def test_repayment_writes_an_audit_row_in_the_same_transaction(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner, phone="0712000111"))["id"]
    await charge(db_session, a, cid, "300")
    entry = (await repay(api, a.owner, cid, "100", "MPESA", reference="REF1")).json()
    rows = await _audits(db_session, a.business_id, "credit.repayment")
    assert len(rows) == 1
    row = rows[0]
    assert row.entity_type == "customer" and row.entity_id == uuid.UUID(cid)
    assert row.actor_user_id == uuid.UUID(a.owner_user_id)
    assert row.after == {
        "entry_id": entry["id"],
        "amount": "100.00",
        "payment_method": "MPESA",
        "balance_after": "200.00",
    }
    assert "0712000111" not in str(row.after) and "Njeri" not in str(row.after)


async def test_failure_after_the_ledger_write_rolls_everything_back(
    api: AsyncClient,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    await charge(db_session, a, cid, "300")
    real_record = audit_service.record

    async def record_then_fail(*args: object, **kwargs: object) -> object:
        await real_record(*args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("simulated failure after audit")

    monkeypatch.setattr("app.services.credit.audit.record", record_then_fail)
    assert (await repay(api, a.owner, cid, "100")).status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert (await adjust(api, a.owner, cid, "50", "INCREASE")).status_code == (
        HTTPStatus.INTERNAL_SERVER_ERROR
    )
    # No entry, no audit, cache untouched.
    assert await db_balance(db_session, cid) == (Decimal("300.00"), Decimal("300.00"))
    assert len((await db_session.scalars(select(CreditTransaction))).all()) == 1
    assert await _audits(db_session, a.business_id, "credit.repayment") == []
    assert await _audits(db_session, a.business_id, "credit.adjust") == []


# --- idempotency ------------------------------------------------------------------------


async def test_same_key_same_payload_replays_without_a_second_entry(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    await charge(db_session, a, cid, "1000")
    key = str(uuid.uuid4())
    first = await api.post(
        f"{CUSTOMERS_URL}/{cid}/repayments",
        headers={**a.owner, "Idempotency-Key": key},
        json={"amount": "400", "payment_method": "CASH"},
    )
    assert first.status_code == HTTPStatus.CREATED, first.text
    retry = await api.post(
        f"{CUSTOMERS_URL}/{cid}/repayments",
        headers={**a.owner, "Idempotency-Key": key},
        json={"amount": "400", "payment_method": "CASH"},
    )
    assert retry.status_code == HTTPStatus.OK  # replay, not a new entry
    assert retry.json() == first.json()
    assert await db_balance(db_session, cid) == (Decimal("600.00"), Decimal("600.00"))
    assert len((await db_session.scalars(select(CreditTransaction))).all()) == 2  # charge + 1
    assert len(await _audits(db_session, a.business_id, "credit.repayment")) == 1


async def test_same_key_different_payload_is_409(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    other = (await create_customer(api, a.owner, name="Other"))["id"]
    await charge(db_session, a, cid, "1000")
    await charge(db_session, a, other, "1000")
    key = str(uuid.uuid4())
    headers = {**a.owner, "Idempotency-Key": key}
    assert (
        await api.post(
            f"{CUSTOMERS_URL}/{cid}/repayments",
            headers=headers,
            json={"amount": "400", "payment_method": "CASH"},
        )
    ).status_code == HTTPStatus.CREATED
    for url, body in (
        (f"{CUSTOMERS_URL}/{cid}/repayments", {"amount": "401", "payment_method": "CASH"}),
        (f"{CUSTOMERS_URL}/{cid}/repayments", {"amount": "400", "payment_method": "MPESA"}),
        (f"{CUSTOMERS_URL}/{other}/repayments", {"amount": "400", "payment_method": "CASH"}),
        (
            f"{CUSTOMERS_URL}/{cid}/adjustments",
            {"amount": "400", "direction": "DECREASE", "reason": "x"},
        ),
    ):
        response = await api.post(url, headers=headers, json=body)
        assert response.status_code == HTTPStatus.CONFLICT, (url, body, response.text)
        assert error_code(response) == "IDEMPOTENCY_CONFLICT"
    assert await db_balance(db_session, cid) == (Decimal("600.00"), Decimal("600.00"))
    assert await db_balance(db_session, other) == (Decimal("1000.00"), Decimal("1000.00"))


async def test_idempotency_keys_are_per_business(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    ca = (await create_customer(api, a.owner))["id"]
    cb = (await create_customer(api, b.owner))["id"]
    await charge(db_session, a, ca, "100")
    await charge(db_session, b, cb, "100")
    key = str(uuid.uuid4())
    for tenant, cid in ((a, ca), (b, cb)):
        response = await api.post(
            f"{CUSTOMERS_URL}/{cid}/repayments",
            headers={**tenant.owner, "Idempotency-Key": key},
            json={"amount": "10", "payment_method": "CASH"},
        )
        assert response.status_code == HTTPStatus.CREATED, response.text


async def test_malformed_idempotency_key_is_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    response = await api.post(
        f"{CUSTOMERS_URL}/{cid}/repayments",
        headers={**a.owner, "Idempotency-Key": "not-a-uuid"},
        json={"amount": "1", "payment_method": "CASH"},
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


# --- adjustments ------------------------------------------------------------------------


async def test_owner_adjusts_up_and_down_with_audit(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    up = await adjust(api, a.owner, cid, "250", "INCREASE", reason="unrecorded sale")
    assert up.status_code == HTTPStatus.CREATED, up.text
    assert (up.json()["entry_type"], up.json()["amount"], up.json()["balance_after"]) == (
        "ADJUSTMENT",
        "250.00",
        "250.00",
    )
    assert up.json()["reason"] == "unrecorded sale"
    down = await adjust(api, a.owner, cid, "50", "DECREASE", reason="goodwill")
    assert down.status_code == HTTPStatus.CREATED
    assert (down.json()["amount"], down.json()["balance_after"]) == ("-50.00", "200.00")
    assert await db_balance(db_session, cid) == (Decimal("200.00"), Decimal("200.00"))
    rows = await _audits(db_session, a.business_id, "credit.adjust")
    assert {(r.before or {}).get("balance") for r in rows} == {"0.00", "250.00"}
    assert {(r.after or {}).get("reason") for r in rows} == {"unrecorded sale", "goodwill"}
    assert all(r.actor_user_id == uuid.UUID(a.owner_user_id) for r in rows)


async def test_adjustment_cannot_take_the_balance_below_zero(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    await charge(db_session, a, cid, "100")
    response = await adjust(api, a.owner, cid, "100.01", "DECREASE")
    assert response.status_code == HTTPStatus.CONFLICT
    assert error_code(response) == "ADJUSTMENT_EXCEEDS_BALANCE"
    exact = await adjust(api, a.owner, cid, "100", "DECREASE")
    assert exact.status_code == HTTPStatus.CREATED and exact.json()["balance_after"] == "0.00"
    assert (await adjust(api, a.owner, cid, "0.01", "DECREASE")).status_code == HTTPStatus.CONFLICT


@pytest.mark.parametrize(
    "body",
    [
        {"amount": "10", "direction": "INCREASE"},  # no reason
        {"amount": "10", "direction": "INCREASE", "reason": ""},
        {"amount": "10", "direction": "INCREASE", "reason": "   "},
        {"amount": "10", "direction": "INCREASE", "reason": "x" * 256},
        {"amount": "10", "direction": "UP", "reason": "r"},
        {"amount": "0", "direction": "INCREASE", "reason": "r"},
        {"amount": "-10", "direction": "INCREASE", "reason": "r"},
        {"amount": "10.005", "direction": "INCREASE", "reason": "r"},
        {"amount": "10", "direction": "INCREASE", "reason": "r", "balance_after": "0"},
    ],
)
async def test_invalid_adjustment_payloads_are_422(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], body: dict[str, str]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    response = await api.post(f"{CUSTOMERS_URL}/{cid}/adjustments", headers=a.owner, json=body)
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, body


async def test_staff_cannot_adjust_but_can_repay_and_read(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    cid = (await create_customer(api, a.owner))["id"]
    await charge(db_session, a, cid, "500")
    denied = await adjust(api, a.staff, cid, "10", "INCREASE")
    assert denied.status_code == HTTPStatus.FORBIDDEN and error_code(denied) == "FORBIDDEN"
    paid = await repay(api, a.staff, cid, "200")
    assert paid.status_code == HTTPStatus.CREATED and paid.json()["created_by"] == a.staff_user_id
    ledger = await api.get(f"{CUSTOMERS_URL}/{cid}/ledger", headers=a.staff)
    assert ledger.status_code == HTTPStatus.OK and ledger.json()["balance"] == "300.00"
    debtors = await api.get(DEBTORS_URL, headers=a.staff)
    assert debtors.status_code == HTTPStatus.OK and debtors.json()[0]["balance"] == "300.00"


# --- ledger -----------------------------------------------------------------------------


async def test_ledger_is_newest_first_and_limited(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner, credit_limit="5000"))["id"]
    for amount in ("100", "200", "300"):
        await charge(db_session, a, cid, amount)
    await repay(api, a.owner, cid, "50")
    body = (await api.get(f"{CUSTOMERS_URL}/{cid}/ledger", headers=a.owner)).json()
    assert body["credit_limit"] == "5000.00" and body["balance"] == "550.00"
    assert [e["balance_after"] for e in body["entries"]] == ["550.00", "600.00", "300.00", "100.00"]
    assert set(body["entries"][0]) == {
        "id",
        "entry_type",
        "amount",
        "balance_after",
        "payment_method",
        "reference",
        "reason",
        "sale_id",
        "occurred_at",
        "created_at",
        "created_by",
    }
    limited = (
        await api.get(f"{CUSTOMERS_URL}/{cid}/ledger", headers=a.owner, params={"limit": 2})
    ).json()
    assert [e["balance_after"] for e in limited["entries"]] == ["550.00", "600.00"]
    assert (
        await api.get(f"{CUSTOMERS_URL}/{cid}/ledger", headers=a.owner, params={"limit": 0})
    ).status_code == 422
    empty = (
        await api.get(
            f"{CUSTOMERS_URL}/{(await create_customer(api, a.owner, name='New'))['id']}/ledger",
            headers=a.owner,
        )
    ).json()
    assert empty["entries"] == [] and empty["balance"] == "0.00"


# --- debtors ----------------------------------------------------------------------------


async def test_debtors_only_positive_balances_sorted_and_isolated(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    small = (await create_customer(api, a.owner, name="Small"))["id"]
    big = (await create_customer(api, a.owner, name="Big", phone="0700000002"))["id"]
    settled = (await create_customer(api, a.owner, name="Settled"))["id"]
    await create_customer(api, a.owner, name="Never bought")
    foreign = (await create_customer(api, b.owner, name="Foreign debtor"))["id"]
    await charge(db_session, a, small, "100")
    await charge(db_session, a, big, "900")
    await charge(db_session, a, settled, "50")
    await repay(api, a.owner, settled, "50")
    await charge(db_session, b, foreign, "5000")

    response = await api.get(DEBTORS_URL, headers=a.owner)
    assert response.status_code == HTTPStatus.OK
    rows = response.json()
    assert [(r["name"], r["balance"]) for r in rows] == [("Big", "900.00"), ("Small", "100.00")]
    assert rows[0]["customer_id"] == big and rows[0]["phone"] == "+254700000002"
    assert rows[0]["oldest_unpaid_charge_at"] is not None
    assert set(rows[0]) == {
        "customer_id",
        "name",
        "phone",
        "balance",
        "credit_limit",
        "oldest_unpaid_charge_at",
    }
    assert "Foreign" not in response.text and "Settled" not in response.text
    assert [r["customer_id"] for r in (await api.get(DEBTORS_URL, headers=b.owner)).json()] == [
        foreign
    ]
    assert len((await api.get(DEBTORS_URL, headers=a.owner, params={"limit": 1})).json()) == 1
    assert (await api.get(DEBTORS_URL, headers=a.owner, params={"limit": 0})).status_code == 422
    assert (await api.get(DEBTORS_URL, headers=a.owner, params={"sort": "name"})).status_code == 422


async def test_debtors_oldest_unpaid_charge_is_fifo(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    first = await charge(db_session, a, cid, "100")
    second = await charge(db_session, a, cid, "200")
    third = await charge(db_session, a, cid, "300")
    # Backdate so occurred_at order is unambiguous (same-transaction rows share created_at).
    first.occurred_at -= timedelta(days=30)
    second.occurred_at -= timedelta(days=20)
    third.occurred_at -= timedelta(days=10)
    await db_session.flush()

    rows = (await api.get(DEBTORS_URL, headers=a.owner)).json()
    assert rows[0]["oldest_unpaid_charge_at"].startswith(first.occurred_at.date().isoformat())
    # Paying 100 clears the first charge; 150 more clears half of the second.
    await repay(api, a.owner, cid, "100")
    rows = (await api.get(DEBTORS_URL, headers=a.owner)).json()
    assert rows[0]["oldest_unpaid_charge_at"].startswith(second.occurred_at.date().isoformat())
    await repay(api, a.owner, cid, "150")
    rows = (await api.get(DEBTORS_URL, headers=a.owner)).json()
    assert rows[0]["oldest_unpaid_charge_at"].startswith(second.occurred_at.date().isoformat())
    await repay(api, a.owner, cid, "50")
    rows = (await api.get(DEBTORS_URL, headers=a.owner)).json()
    assert rows[0]["oldest_unpaid_charge_at"].startswith(third.occurred_at.date().isoformat())


async def test_debtors_sort_by_age(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    recent = (await create_customer(api, a.owner, name="Recent"))["id"]
    old = (await create_customer(api, a.owner, name="Old"))["id"]
    await charge(db_session, a, recent, "900")
    entry = await charge(db_session, a, old, "100")
    entry.occurred_at -= timedelta(days=60)
    await db_session.flush()
    by_balance = (await api.get(DEBTORS_URL, headers=a.owner)).json()
    assert [r["name"] for r in by_balance] == ["Recent", "Old"]
    by_age = (await api.get(DEBTORS_URL, headers=a.owner, params={"sort": "age"})).json()
    assert [r["name"] for r in by_age] == ["Old", "Recent"]


# --- credit limit (service primitive; sales wires it) -----------------------------------


async def test_credit_limit_semantics(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    limited = (await create_customer(api, a.owner, name="Limited", credit_limit="1000"))["id"]
    unlimited = (await create_customer(api, a.owner, name="Unlimited"))["id"]
    no_credit = (await create_customer(api, a.owner, name="Cash only", credit_limit="0"))["id"]
    await charge(db_session, a, limited, "600")
    customers = {
        cid: await db_session.get(Customer, uuid.UUID(cid))
        for cid in (limited, unlimited, no_credit)
    }
    lim = customers[limited]
    assert lim is not None
    await db_session.refresh(lim)

    within = credit_service.evaluate_credit_limit(lim, Decimal("399.99"))
    exactly = credit_service.evaluate_credit_limit(lim, Decimal("400"))
    above = credit_service.evaluate_credit_limit(lim, Decimal("400.01"))
    assert (within.exceeded, exactly.exceeded, above.exceeded) == (False, False, True)
    assert above.projected_balance == Decimal("1000.01")

    unl = customers[unlimited]
    assert (
        unl is not None
        and not credit_service.evaluate_credit_limit(unl, Decimal("1000000")).exceeded
    )
    zero = customers[no_credit]
    assert zero is not None and credit_service.evaluate_credit_limit(zero, Decimal("0.01")).exceeded

    # FR-G5: STAFF blocked, OWNER warned (409) unless they override.
    for role in (MembershipRole.STAFF, MembershipRole.OWNER):
        with pytest.raises(credit_service.CreditLimitExceededError) as exc_info:
            credit_service.enforce_credit_limit(lim, Decimal("500"), role=role)
        assert exc_info.value.code == "CREDIT_LIMIT_EXCEEDED"
        assert exc_info.value.details == {
            "balance": "600.00",
            "credit_limit": "1000.00",
            "projected_balance": "1100.00",
            "owner_may_override": role is MembershipRole.OWNER,
        }
    with pytest.raises(credit_service.CreditLimitExceededError):
        credit_service.enforce_credit_limit(
            lim, Decimal("500"), role=MembershipRole.STAFF, owner_override=True
        )
    ok = credit_service.enforce_credit_limit(
        lim, Decimal("500"), role=MembershipRole.OWNER, owner_override=True
    )
    assert ok.exceeded and ok.projected_balance == Decimal("1100.00")
    assert not credit_service.enforce_credit_limit(
        lim, Decimal("400"), role=MembershipRole.STAFF
    ).exceeded


# --- authorization / isolation / privacy ---------------------------------------------


async def test_unauthenticated_and_inactive_business(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    cid = (await create_customer(api, a.owner))["id"]
    for call in (
        api.get(f"{CUSTOMERS_URL}/{cid}/ledger"),
        api.get(DEBTORS_URL),
        api.post(
            f"{CUSTOMERS_URL}/{cid}/repayments", json={"amount": "1", "payment_method": "CASH"}
        ),
        api.post(
            f"{CUSTOMERS_URL}/{cid}/adjustments",
            json={"amount": "1", "direction": "INCREASE", "reason": "r"},
        ),
    ):
        assert (await call).status_code == HTTPStatus.UNAUTHORIZED
    await set_business_active(db_session, uuid.UUID(a.business_id), False)
    for call in (
        api.get(f"{CUSTOMERS_URL}/{cid}/ledger", headers=a.owner),
        api.get(DEBTORS_URL, headers=a.owner),
        repay(api, a.owner, cid, "1"),
        adjust(api, a.owner, cid, "1", "INCREASE"),
    ):
        response = await call
        assert response.status_code == HTTPStatus.FORBIDDEN
        assert error_code(response) == "BUSINESS_INACTIVE"


async def test_cross_tenant_account_operations_are_404(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    cid = (await create_customer(api, b.owner, name="Beta Debtor", phone="0700000009"))["id"]
    await charge(db_session, b, cid, "700")
    for call in (
        api.get(f"{CUSTOMERS_URL}/{cid}/ledger", headers=a.owner),
        repay(api, a.owner, cid, "1"),
        adjust(api, a.owner, cid, "1", "INCREASE"),
        adjust(api, a.owner, cid, "1", "DECREASE"),
    ):
        response = await call
        assert response.status_code == HTTPStatus.NOT_FOUND, response.text
        assert error_code(response) == "NOT_FOUND"
        assert "Beta" not in response.text and "700" not in response.text
    assert await db_balance(db_session, cid) == (Decimal("700.00"), Decimal("700.00"))
    assert (
        await api.get(f"{CUSTOMERS_URL}/{uuid.uuid4()}/ledger", headers=a.owner)
    ).status_code == 404


async def test_customer_pii_and_secrets_stay_out_of_logs(
    api: AsyncClient,
    db_session: AsyncSession,
    tenants: tuple[Tenant, Tenant],
    caplog: pytest.LogCaptureFixture,
) -> None:
    a, _ = tenants
    logging.getLogger().addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG)
    cid = (await create_customer(api, a.owner, name="Very Private", phone="0799000111"))["id"]
    await charge(db_session, a, cid, "100")
    assert (await repay(api, a.owner, cid, "40", "MPESA", reference="SECRETREF")).status_code == 201
    assert (
        await adjust(api, a.owner, cid, "5", "DECREASE", reason="private reason")
    ).status_code == 201
    rendered = "\n".join(JsonFormatter().format(r) for r in caplog.records)
    for value in ("Very Private", "+254799000111", "0799000111", "SECRETREF", "private reason"):
        assert value not in rendered
    assert a.owner["Authorization"].removeprefix("Bearer ") not in rendered
