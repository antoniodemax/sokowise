"""`/api/v1/mpesa`: paste, match, ignore, repayment, reverse links and reconciliation.

Messages are synthetic (names, masked numbers, codes `RK1TEST0xx`).
"""

import uuid
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.models import AuditLog, MpesaMessage
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import error_code
from tests.db.isolation import Tenant
from tests.db.sales_helpers import CUSTOMERS_URL, make_customer, make_product, sale_payload, sell

pytestmark = [pytest.mark.db, pytest.mark.anyio]

URL = "/api/v1/mpesa"
NAIROBI = ZoneInfo("Africa/Nairobi")


def sms(code: str, amount: str, when: datetime | None = None, *, kind: str = "pochi") -> str:
    """A synthetic received-money SMS at `when` (aware) or now, in Nairobi wording."""
    local = (when or datetime.now(UTC)).astimezone(NAIROBI)
    stamp = f"{local.day}/{local.month}/{local.strftime('%y')} at {local.strftime('%-I:%M %p')}"
    tail = {
        "pochi": "New business balance is Ksh9,999.00.",
        "send": "New M-PESA balance is Ksh9,999.00.",
    }[kind]
    return (
        f"{code} Confirmed. You have received Ksh{amount} from JANE TESTER 0712***456 "
        f"on {stamp}. {tail}"
    )


async def paste(api: AsyncClient, headers: dict[str, str], text: str) -> tuple[int, Any]:
    response = await api.post(f"{URL}/messages", headers=headers, json={"text": text})
    return response.status_code, response.json()


def _code(body: Any) -> str:
    code: str = body["error"]["code"]
    return code


async def _rows(session: AsyncSession, business_id: str) -> list[MpesaMessage]:
    return list(
        await session.scalars(
            select(MpesaMessage)
            .where(MpesaMessage.business_id == uuid.UUID(business_id))
            .execution_options(populate_existing=True)
        )
    )


async def _audits(session: AsyncSession, business_id: str, action: str) -> list[AuditLog]:
    return list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.business_id == uuid.UUID(business_id), AuditLog.action == action)
            .execution_options(populate_existing=True)
        )
    )


# --- paste ---------------------------------------------------------------------------


async def test_paste_stores_a_received_message_as_unmatched_with_no_candidates(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    status, body = await paste(api, a.owner, sms("RK1TEST001", "1,000.00"))
    assert status == HTTPStatus.CREATED, body
    assert body["status"] == "UNMATCHED" and body["code"] == "RK1TEST001"
    assert body["amount"] == "1000.00" and body["kind"] == "POCHI"
    assert body["sender_name"] == "JANE TESTER" and body["sender_phone_masked"] == "0712***456"
    assert body["candidates"] == {"payments": [], "customers": []}
    assert body["payment_id"] is None and body["sale_id"] is None
    audits = await _audits(db_session, a.business_id, "mpesa.paste")
    assert len(audits) == 1 and audits[0].after is not None
    assert audits[0].after["code"] == "RK1TEST001"
    # No name, phone or raw text in the audit payload.
    assert "JANE" not in str(audits[0].after) and "0712" not in str(audits[0].after)


async def test_same_code_pasted_twice_is_a_replay(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    first = await paste(api, a.owner, sms("RK1TEST002", "500.00"))
    again = await paste(api, a.owner, sms("RK1TEST002", "500.00").lower())
    assert first[0] == HTTPStatus.CREATED and again[0] == HTTPStatus.OK
    assert again[1]["id"] == first[1]["id"]
    assert len(await _rows(db_session, a.business_id)) == 1
    assert len(await _audits(db_session, a.business_id, "mpesa.paste")) == 1


async def test_customer_side_message_is_refused_and_not_stored(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    sent = (
        "RK1TEST005 Confirmed. Ksh1,000.00 sent to JANE TESTER 0712***456 on 18/9/26 at "
        "2:15 PM. New M-PESA balance is Ksh4,000.00. Transaction cost, Ksh0.00."
    )
    status, body = await paste(api, a.owner, sent)
    assert status == HTTPStatus.UNPROCESSABLE_ENTITY
    assert body["error"]["code"] == "NOT_MONEY_RECEIVED"
    assert await _rows(db_session, a.business_id) == []


async def test_unreadable_text_is_kept_as_unparsed(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    status, body = await paste(api, a.owner, "Hello, please send two crates tomorrow")
    assert status == HTTPStatus.CREATED
    assert body["status"] == "UNPARSED" and body["code"] is None and body["amount"] is None
    assert body["raw_text"] == "Hello, please send two crates tomorrow"
    assert body["candidates"] is None
    (row,) = await _rows(db_session, a.business_id)
    assert row.status.value == "UNPARSED"


@pytest.mark.parametrize("text", ["", "short", "x" * 1001])
async def test_paste_validation(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], text: str
) -> None:
    a, _ = tenants
    status, body = await paste(api, a.owner, text)
    assert status == HTTPStatus.UNPROCESSABLE_ENTITY and _code(body) == "VALIDATION_ERROR"


# --- rules (a) and (b): the record came first ----------------------------------------


async def test_paste_links_to_the_sale_that_already_carries_the_code(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, price="500")
    # Typed with different case and stray spaces; the code still matches.
    ref = " rk1test010 "
    sale = await sell(
        api,
        a.owner,
        {
            **sale_payload([(p["id"], "2")]),
            "payments": [{"method": "MPESA", "amount": "1000", "reference": ref}],
        },
    )
    status, body = await paste(api, a.owner, sms("RK1TEST010", "1,000.00"))
    assert status == HTTPStatus.CREATED
    assert body["status"] == "MATCHED" and body["sale_id"] == sale["id"]
    assert body["payment_id"] == sale["payments"][0]["id"] and body["candidates"] is None


async def test_paste_does_not_link_to_a_voided_sale(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, price="500")
    sale = await sell(
        api,
        a.owner,
        {
            **sale_payload([(p["id"], "1")]),
            "payments": [{"method": "MPESA", "amount": "500", "reference": "RK1TEST011"}],
        },
    )
    void = await api.post(f"/api/v1/sales/{sale['id']}/void", headers=a.owner, json={"reason": "x"})
    assert void.status_code == HTTPStatus.OK
    status, body = await paste(api, a.owner, sms("RK1TEST011", "500.00"))
    assert status == HTTPStatus.CREATED and body["status"] == "UNMATCHED"


async def test_paste_links_to_the_repayment_that_carries_the_code(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, price="500")
    c = await make_customer(api, a.owner)
    await sell(
        api, a.owner, sale_payload([(p["id"], "2")], [("CREDIT", "1000")], customer_id=c["id"])
    )
    repay = await api.post(
        f"{CUSTOMERS_URL}/{c['id']}/repayments",
        headers=a.owner,
        json={"amount": "400", "payment_method": "MPESA", "reference": "RK1TEST012"},
    )
    assert repay.status_code == HTTPStatus.CREATED
    status, body = await paste(api, a.owner, sms("RK1TEST012", "400.00"))
    assert status == HTTPStatus.CREATED
    assert body["status"] == "MATCHED"
    assert body["credit_transaction_id"] == repay.json()["id"]
    assert body["customer_id"] == c["id"] and body["payment_id"] is None


# --- rule (c): suggestions, never applied ---------------------------------------------


async def test_candidates_are_suggested_not_applied(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    p = await make_product(api, a.owner, price="500", stock="50")
    now = datetime.now(UTC)
    near = await sell(api, a.owner, sale_payload([(p["id"], "2")], [("MPESA", "1000")]))
    other_amount = await sell(api, a.owner, sale_payload([(p["id"], "1")], [("MPESA", "500")]))
    cash = await sell(api, a.owner, sale_payload([(p["id"], "2")], [("CASH", "1000")]))
    far = await sell(
        api,
        a.owner,
        sale_payload(
            [(p["id"], "2")], [("MPESA", "1000")], sold_at=(now - timedelta(hours=5)).isoformat()
        ),
    )
    referenced = await sell(
        api,
        a.owner,
        {
            **sale_payload([(p["id"], "2")]),
            "payments": [{"method": "MPESA", "amount": "1000", "reference": "RK1TEST099"}],
        },
    )
    await paste(api, a.owner, sms("RK1TEST099", "1,000.00"))  # consumes `referenced`
    c_match = await make_customer(api, a.owner, name="Ends 456", phone="0700111456")
    await make_customer(api, a.owner, name="Ends 999", phone="0700111999")

    status, body = await paste(api, a.owner, sms("RK1TEST020", "1,000.00", now))
    assert status == HTTPStatus.CREATED and body["status"] == "UNMATCHED"
    suggested = {c["sale_id"] for c in body["candidates"]["payments"]}
    assert suggested == {near["id"]}
    assert not {other_amount["id"], cash["id"], far["id"], referenced["id"]} & suggested
    assert [c["customer_id"] for c in body["candidates"]["customers"]] == [c_match["id"]]


async def test_explicit_match_to_a_sale_and_cross_tenant_targets(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner, price="500")
    sale = await sell(api, a.owner, sale_payload([(p["id"], "2")], [("MPESA", "1000")]))
    payment_id = sale["payments"][0]["id"]
    _, msg = await paste(api, a.owner, sms("RK1TEST030", "1,000.00"))

    pb = await make_product(api, b.owner, price="500")
    foreign = await sell(api, b.owner, sale_payload([(pb["id"], "2")], [("MPESA", "1000")]))
    denied = await api.post(
        f"{URL}/messages/{msg['id']}/match",
        headers=a.owner,
        json={"payment_id": foreign["payments"][0]["id"]},
    )
    assert denied.status_code == HTTPStatus.NOT_FOUND

    both = await api.post(
        f"{URL}/messages/{msg['id']}/match",
        headers=a.owner,
        json={"payment_id": payment_id, "credit_transaction_id": str(uuid.uuid4())},
    )
    assert both.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    matched = await api.post(
        f"{URL}/messages/{msg['id']}/match", headers=a.staff, json={"payment_id": payment_id}
    )
    assert matched.status_code == HTTPStatus.OK, matched.text
    assert matched.json()["status"] == "MATCHED" and matched.json()["sale_id"] == sale["id"]
    twice = await api.post(
        f"{URL}/messages/{msg['id']}/match", headers=a.owner, json={"payment_id": payment_id}
    )
    assert twice.status_code == HTTPStatus.CONFLICT
    assert error_code(twice) == "MPESA_INVALID_TRANSITION"
    audits = await _audits(db_session, a.business_id, "mpesa.match")
    assert len(audits) == 1 and audits[0].after is not None and audits[0].after["via"] == "manual"


# --- reverse hooks: the message came first --------------------------------------------


async def test_sale_recorded_later_with_the_code_links_the_message(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    _, msg = await paste(api, a.owner, sms("RK1TEST040", "1,000.00"))
    assert msg["status"] == "UNMATCHED"
    p = await make_product(api, a.owner, price="500")
    sale = await sell(
        api,
        a.staff,
        {
            **sale_payload([(p["id"], "2")]),
            "payments": [{"method": "MPESA", "amount": "1000", "reference": "rk1test040"}],
        },
    )
    after = (await api.get(f"{URL}/messages/{msg['id']}", headers=a.owner)).json()
    assert after["status"] == "MATCHED" and after["sale_id"] == sale["id"]
    audits = await _audits(db_session, a.business_id, "mpesa.match")
    assert len(audits) == 1 and audits[0].after is not None
    assert audits[0].after["via"] == "sale.create"

    # Voiding the sale sets the message free again, audited.
    void = await api.post(
        f"/api/v1/sales/{sale['id']}/void", headers=a.owner, json={"reason": "typo"}
    )
    assert void.status_code == HTTPStatus.OK
    freed = (await api.get(f"{URL}/messages/{msg['id']}", headers=a.owner)).json()
    assert freed["status"] == "UNMATCHED" and freed["payment_id"] is None
    assert len(await _audits(db_session, a.business_id, "mpesa.unlink")) == 1


async def test_repayment_recorded_later_with_the_code_links_the_message(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner, price="500")
    c = await make_customer(api, a.owner)
    await sell(
        api, a.owner, sale_payload([(p["id"], "2")], [("CREDIT", "1000")], customer_id=c["id"])
    )
    _, msg = await paste(api, a.owner, sms("RK1TEST041", "300.00"))
    repay = await api.post(
        f"{CUSTOMERS_URL}/{c['id']}/repayments",
        headers=a.staff,
        json={"amount": "300", "payment_method": "MPESA", "reference": "RK1TEST041"},
    )
    assert repay.status_code == HTTPStatus.CREATED
    after = (await api.get(f"{URL}/messages/{msg['id']}", headers=a.owner)).json()
    assert after["status"] == "MATCHED" and after["customer_id"] == c["id"]


async def test_record_repayment_from_message(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner, price="500")
    c = await make_customer(api, a.owner)
    await sell(
        api, a.owner, sale_payload([(p["id"], "2")], [("CREDIT", "1000")], customer_id=c["id"])
    )
    _, msg = await paste(api, a.owner, sms("RK1TEST042", "250.00"))
    done = await api.post(
        f"{URL}/messages/{msg['id']}/repayment", headers=a.staff, json={"customer_id": c["id"]}
    )
    assert done.status_code == HTTPStatus.OK, done.text
    assert done.json()["status"] == "MATCHED" and done.json()["customer_id"] == c["id"]
    balance = (await api.get(f"{CUSTOMERS_URL}/{c['id']}", headers=a.owner)).json()["balance"]
    assert balance == "750.00"
    ledger = (await api.get(f"{CUSTOMERS_URL}/{c['id']}/ledger", headers=a.owner)).json()
    entry = ledger["entries"][0]
    assert entry["entry_type"] == "REPAYMENT" and entry["reference"] == "RK1TEST042"
    assert entry["payment_method"] == "MPESA" and entry["amount"] == "-250.00"
    # A second attempt is refused: the message is already matched, and the ledger is unchanged.
    again = await api.post(
        f"{URL}/messages/{msg['id']}/repayment", headers=a.owner, json={"customer_id": c["id"]}
    )
    assert again.status_code == HTTPStatus.CONFLICT
    assert (await api.get(f"{CUSTOMERS_URL}/{c['id']}", headers=a.owner)).json()[
        "balance"
    ] == "750.00"


async def test_repayment_from_message_beyond_balance_needs_overpayment_flag(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    c = await make_customer(api, a.owner)
    _, msg = await paste(api, a.owner, sms("RK1TEST043", "250.00"))
    refused = await api.post(
        f"{URL}/messages/{msg['id']}/repayment", headers=a.owner, json={"customer_id": c["id"]}
    )
    assert refused.status_code == HTTPStatus.CONFLICT
    assert error_code(refused) == "REPAYMENT_EXCEEDS_BALANCE"
    still = (await api.get(f"{URL}/messages/{msg['id']}", headers=a.owner)).json()
    assert still["status"] == "UNMATCHED"


# --- ignore ---------------------------------------------------------------------------


async def test_ignore_is_owner_only_and_refuses_matched_messages(
    api: AsyncClient, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    _, msg = await paste(api, a.staff, sms("RK1TEST050", "80.00"))
    staff = await api.post(
        f"{URL}/messages/{msg['id']}/ignore", headers=a.staff, json={"reason": "refund"}
    )
    assert staff.status_code == HTTPStatus.FORBIDDEN
    owner = await api.post(
        f"{URL}/messages/{msg['id']}/ignore", headers=a.owner, json={"reason": "refund"}
    )
    assert owner.status_code == HTTPStatus.OK and owner.json()["status"] == "IGNORED"
    assert owner.json()["ignore_reason"] == "refund"
    assert len(await _audits(db_session, a.business_id, "mpesa.ignore")) == 1
    # Idempotent.
    assert (
        await api.post(f"{URL}/messages/{msg['id']}/ignore", headers=a.owner, json={})
    ).status_code == HTTPStatus.OK
    # Unparsed rows can be ignored; matched rows cannot.
    _, junk = await paste(api, a.owner, "not an mpesa message at all")
    assert (await api.post(f"{URL}/messages/{junk['id']}/ignore", headers=a.owner, json={})).json()[
        "status"
    ] == "IGNORED"
    p = await make_product(api, a.owner, price="500")
    await sell(
        api,
        a.owner,
        {
            **sale_payload([(p["id"], "1")]),
            "payments": [{"method": "MPESA", "amount": "500", "reference": "RK1TEST051"}],
        },
    )
    _, matched = await paste(api, a.owner, sms("RK1TEST051", "500.00"))
    refused = await api.post(f"{URL}/messages/{matched['id']}/ignore", headers=a.owner, json={})
    assert refused.status_code == HTTPStatus.CONFLICT


# --- list and reconciliation ----------------------------------------------------------


async def test_list_filters_by_status_and_day_newest_first(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    now = datetime.now(UTC)
    await paste(api, a.owner, sms("RK1TEST060", "10.00", now - timedelta(minutes=30)))
    await paste(api, a.owner, sms("RK1TEST061", "20.00", now - timedelta(minutes=10)))
    await paste(api, a.owner, "garbage that is long enough")
    listed = (await api.get(f"{URL}/messages", headers=a.staff)).json()
    assert [m["code"] for m in listed][:3] == [None, "RK1TEST061", "RK1TEST060"]
    unmatched = (await api.get(f"{URL}/messages?status=UNMATCHED", headers=a.owner)).json()
    assert [m["code"] for m in unmatched] == ["RK1TEST061", "RK1TEST060"]
    assert all(m["candidates"] is None for m in listed)  # list views are light


async def test_reconciliation_for_a_local_day(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    today = datetime.now(NAIROBI).date()
    # 23:30 local yesterday stays on yesterday; 00:10 local today is today.
    late_yesterday = datetime.combine(
        today - timedelta(days=1), datetime.min.time(), NAIROBI
    ).replace(hour=23, minute=30)
    early_today = datetime.combine(today, datetime.min.time(), NAIROBI).replace(hour=0, minute=10)
    p = await make_product(api, a.owner, price="500", stock="50")
    sale = await sell(
        api,
        a.owner,
        {
            **sale_payload([(p["id"], "2")]),
            "payments": [{"method": "MPESA", "amount": "1000", "reference": "RK1TEST070"}],
            "sold_at": early_today.isoformat(),
        },
    )
    assert sale["status"] == "COMPLETED"
    await paste(api, a.owner, sms("RK1TEST070", "1,000.00", early_today))  # matched
    await paste(api, a.owner, sms("RK1TEST071", "300.00", early_today))  # unmatched
    _, ignored = await paste(api, a.owner, sms("RK1TEST072", "50.00", early_today))
    await api.post(f"{URL}/messages/{ignored['id']}/ignore", headers=a.owner, json={})
    await paste(api, a.owner, sms("RK1TEST073", "999.00", late_yesterday))  # other day
    await paste(api, a.owner, "unreadable text pasted today")

    r = (await api.get(f"{URL}/reconciliation?date={today.isoformat()}", headers=a.staff)).json()
    assert r["date"] == today.isoformat()
    assert (r["received_count"], r["received_total"]) == (2, "1300.00")
    assert (r["matched_count"], r["matched_total"]) == (1, "1000.00")
    assert (r["unmatched_count"], r["unmatched_total"]) == (1, "300.00")
    assert r["ignored_count"] == 1 and r["unparsed_count"] == 1
    summary = (await api.get("/api/v1/analytics/summary?period=today", headers=a.owner)).json()
    assert r["recorded_in_app"] == summary["cash_collected"]["MPESA"] == "1000.00"
    yesterday = (
        await api.get(
            f"{URL}/reconciliation?date={(today - timedelta(days=1)).isoformat()}", headers=a.owner
        )
    ).json()
    assert yesterday["received_count"] == 1 and yesterday["received_total"] == "999.00"


async def test_unauthenticated_is_401(api: AsyncClient) -> None:
    assert (await api.get(f"{URL}/messages")).status_code == HTTPStatus.UNAUTHORIZED
