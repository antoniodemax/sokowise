"""Copilot proposals (PRD FR-J7): the model proposes, only the owner's confirm applies.

The fake provider plays scripted `propose_*` tool calls; no model is involved.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from typing import Any

import pytest
from app.ai.provider import ProviderResponse, ToolCall, Usage
from app.models import AIMessage, AuditLog
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.ai_helpers import FakeProvider, ask, make_ai_api, new_conversation, text_response
from tests.db.conftest import ApiFactory
from tests.db.isolation import Tenant
from tests.db.sales_helpers import CUSTOMERS_URL, make_customer, make_product, sale_payload, sell

pytestmark = [pytest.mark.db, pytest.mark.anyio]

AI_URL = "/api/v1/ai"


def proposal_turn(name: str, payload: dict[str, Any], text: str = "Tap Confirm.") -> list[Any]:
    """One turn: the model calls a propose tool and (in the same response) says one line."""
    return [
        ProviderResponse(
            content=[
                {"type": "text", "text": text},
                {"type": "tool_use", "id": "tu_p", "name": name, "input": payload},
            ],
            text=text,
            tool_calls=[ToolCall(id="tu_p", name=name, input=payload)],
            stop_reason="tool_use",
            usage=Usage(input_tokens=120, output_tokens=30),
            model="claude-test",
        )
    ]


async def propose(
    api: AsyncClient, headers: dict[str, str], provider: FakeProvider, prompt: str
) -> tuple[str, dict[str, Any]]:
    conversation_id = await new_conversation(api, headers)
    response = await ask(api, headers, conversation_id, prompt)
    assert response.status_code == HTTPStatus.OK, response.text
    return conversation_id, response.json()["assistant_message"]


async def _audits(session: AsyncSession, business_id: str, action: str) -> list[AuditLog]:
    return list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.business_id == uuid.UUID(business_id), AuditLog.action == action)
            .execution_options(populate_existing=True)
        )
    )


async def test_product_proposal_is_stored_pending_and_applied_only_on_confirm(
    api_factory: ApiFactory, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    provider = FakeProvider(
        proposal_turn(
            "propose_product",
            {
                "name": "Sukari 1kg",
                "selling_price": "160",
                "cost_price": "135",
                "unit": "piece",
                "track_inventory": True,
                "opening_stock": None,
            },
            "Sukari 1kg at KSh 160 — tap Confirm to add it.",
        )
    )
    api = await make_ai_api(api_factory, provider)
    conversation_id, message = await propose(
        api, a.owner, provider, "add sukari 1kg at 160, cost 135"
    )
    assert message["content"] == "Sukari 1kg at KSh 160 — tap Confirm to add it."
    assert message["proposal"]["kind"] == "product" and message["proposal"]["status"] == "PENDING"
    assert Decimal(message["proposal"]["payload"]["selling_price"]) == Decimal("160")
    # Nothing was written by the model's turn.
    assert (await api.get("/api/v1/products", headers=a.owner)).json() == []

    # Stock now needs a cost (the INITIAL movement carries one): a plain 422, never a 500,
    # and the proposal stays pending so the owner can add the cost and confirm again.
    url = f"{AI_URL}/conversations/{conversation_id}/messages/{message['id']}/confirm"
    no_cost = await api.post(
        url,
        headers=a.owner,
        json={
            "payload": {
                **message["proposal"]["payload"],
                "cost_price": None,
                "opening_stock": "12",
            }
        },
    )
    assert no_cost.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, no_cost.text
    assert no_cost.json()["error"]["code"] == "PROPOSAL_INVALID"
    assert "cost price" in no_cost.json()["error"]["message"]
    assert (await api.get("/api/v1/products", headers=a.owner)).json() == []

    # The owner edits the price and adds stock, then confirms.
    confirmed = await api.post(
        url,
        headers=a.owner,
        json={
            "payload": {
                **message["proposal"]["payload"],
                "selling_price": "165",
                "opening_stock": "12",
            }
        },
    )
    assert confirmed.status_code == HTTPStatus.OK, confirmed.text
    body = confirmed.json()
    assert body["kind"] == "product" and body["message"]["proposal"]["status"] == "APPLIED"
    products = (await api.get("/api/v1/products", headers=a.owner)).json()
    assert [
        (p["name"], p["selling_price"], p["cost_price"], p["stock_quantity"]) for p in products
    ] == [("Sukari 1kg", "165.00", "135.00", "12.000")]
    assert body["entity_id"] == products[0]["id"]
    audits = await _audits(db_session, a.business_id, "ai.proposal_apply")
    assert len(audits) == 1 and audits[0].after is not None
    assert audits[0].after["edited"] is True and audits[0].after["kind"] == "product"

    # A second confirm is refused; the product is not duplicated.
    again = await api.post(
        f"{AI_URL}/conversations/{conversation_id}/messages/{message['id']}/confirm",
        headers=a.owner,
        json={"payload": message["proposal"]["payload"]},
    )
    assert again.status_code == HTTPStatus.CONFLICT
    assert again.json()["error"]["code"] == "PROPOSAL_NOT_PENDING"
    assert len((await api.get("/api/v1/products", headers=a.owner)).json()) == 1


async def test_sale_proposal_goes_through_the_sales_service_and_replays_on_retry(
    api_factory: ApiFactory, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    api = await make_ai_api(api_factory, None)
    p = await make_product(api, a.owner, price="160", cost="135", stock="10")
    c = await make_customer(api, a.owner)
    provider = FakeProvider(
        proposal_turn(
            "propose_sale",
            {
                "lines": [{"product_id": p["id"], "quantity": "3", "unit_price": None}],
                "payments": [
                    {"method": "CASH", "amount": "300", "reference": None},
                    {"method": "CREDIT", "amount": "180", "reference": None},
                ],
                "customer_id": c["id"],
                "note": None,
            },
        )
    )
    api = await make_ai_api(api_factory, provider)
    conversation_id, message = await propose(
        api, a.owner, provider, "sold 3 sugar, 300 cash rest on deni for Mama Njeri"
    )
    payload = message["proposal"]["payload"]
    url = f"{AI_URL}/conversations/{conversation_id}/messages/{message['id']}/confirm"
    first = await api.post(url, headers=a.owner, json={"payload": payload})
    assert first.status_code == HTTPStatus.OK, first.text
    sale_id = first.json()["entity_id"]
    sale = (await api.get(f"/api/v1/sales/{sale_id}", headers=a.owner)).json()
    assert sale["total_amount"] == "480.00" and sale["customer_id"] == c["id"]
    assert (await api.get(f"/api/v1/products/{p['id']}", headers=a.owner)).json()[
        "stock_quantity"
    ] == "7.000"
    assert (await api.get(f"{CUSTOMERS_URL}/{c['id']}", headers=a.owner)).json()[
        "balance"
    ] == "180.00"

    # The proposal is APPLIED, so a retry is refused rather than recorded twice; and even a
    # direct replay of the service uses the message-derived idempotency key (one sale).
    retry = await api.post(url, headers=a.owner, json={"payload": payload})
    assert retry.status_code == HTTPStatus.CONFLICT
    assert len((await api.get("/api/v1/sales", headers=a.owner)).json()) == 1


async def test_sale_proposal_service_errors_leave_the_proposal_pending(
    api_factory: ApiFactory, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    api = await make_ai_api(api_factory, None)
    p = await make_product(api, a.owner, price="160", stock="2")
    provider = FakeProvider(
        proposal_turn(
            "propose_sale",
            {
                "lines": [{"product_id": p["id"], "quantity": "5", "unit_price": None}],
                "payments": [{"method": "CASH", "amount": "800", "reference": None}],
                "customer_id": None,
                "note": None,
            },
        )
    )
    api = await make_ai_api(api_factory, provider)
    conversation_id, message = await propose(api, a.owner, provider, "sold 5 sugar cash")
    url = f"{AI_URL}/conversations/{conversation_id}/messages/{message['id']}/confirm"
    refused = await api.post(url, headers=a.owner, json={"payload": message["proposal"]["payload"]})
    assert refused.status_code == HTTPStatus.CONFLICT
    assert refused.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    detail = (await api.get(f"{AI_URL}/conversations/{conversation_id}", headers=a.owner)).json()
    assert detail["messages"][-1]["proposal"]["status"] == "PENDING"
    # The owner fixes the quantity and confirms.
    fixed = {
        **message["proposal"]["payload"],
        "lines": [{"product_id": p["id"], "quantity": "2", "unit_price": None}],
        "payments": [{"method": "CASH", "amount": "320", "reference": None}],
    }
    ok = await api.post(url, headers=a.owner, json={"payload": fixed})
    assert ok.status_code == HTTPStatus.OK, ok.text


async def test_repayment_and_restock_proposals(
    api_factory: ApiFactory, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    api = await make_ai_api(api_factory, None)
    p = await make_product(api, a.owner, price="160", cost="135", stock="10")
    c = await make_customer(api, a.owner)
    await sell(
        api, a.owner, sale_payload([(p["id"], "2")], [("CREDIT", "320")], customer_id=c["id"])
    )
    provider = FakeProvider(
        proposal_turn(
            "propose_repayment",
            {"customer_id": c["id"], "amount": "120", "method": "MPESA", "reference": "RK1TESTAI1"},
        )
        + proposal_turn(
            "propose_restock",
            {
                "product_id": p["id"],
                "quantity": "24",
                "unit_cost": "130",
                "supplier_name": "Kamau Wholesalers",
            },
        )
    )
    api = await make_ai_api(api_factory, provider)
    conversation_id, repay = await propose(
        api, a.owner, provider, "Mama Njeri paid 120 by mpesa RK1TESTAI1"
    )
    done = await api.post(
        f"{AI_URL}/conversations/{conversation_id}/messages/{repay['id']}/confirm",
        headers=a.owner,
        json={"payload": repay["proposal"]["payload"]},
    )
    assert done.status_code == HTTPStatus.OK, done.text
    assert (await api.get(f"{CUSTOMERS_URL}/{c['id']}", headers=a.owner)).json()[
        "balance"
    ] == "200.00"
    ledger = (await api.get(f"{CUSTOMERS_URL}/{c['id']}/ledger", headers=a.owner)).json()[
        "entries"
    ][0]
    assert ledger["entry_type"] == "REPAYMENT" and ledger["reference"] == "RK1TESTAI1"

    response = await ask(api, a.owner, conversation_id, "I bought 24 sugar at 130 from Kamau")
    restock = response.json()["assistant_message"]
    assert restock["proposal"]["kind"] == "restock"
    done = await api.post(
        f"{AI_URL}/conversations/{conversation_id}/messages/{restock['id']}/confirm",
        headers=a.owner,
        json={"payload": restock["proposal"]["payload"]},
    )
    assert done.status_code == HTTPStatus.OK, done.text
    assert (await api.get(f"/api/v1/products/{p['id']}", headers=a.owner)).json()[
        "stock_quantity"
    ] == "32.000"
    movements = (
        await api.get(f"/api/v1/inventory/movements?product_id={p['id']}", headers=a.owner)
    ).json()
    restocks = [m for m in movements if m["movement_type"] == "RESTOCK"]
    assert len(restocks) == 1 and restocks[0]["supplier_name"] == "Kamau Wholesalers"
    assert restocks[0]["quantity_delta"] == "24.000"


async def test_foreign_and_invalid_ids_cannot_act(
    api_factory: ApiFactory, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    api = await make_ai_api(api_factory, None)
    foreign = await make_product(api, b.owner, price="10", stock="50")
    provider = FakeProvider(
        proposal_turn(
            "propose_sale",
            {
                "lines": [{"product_id": foreign["id"], "quantity": "1", "unit_price": None}],
                "payments": [{"method": "CASH", "amount": "10", "reference": None}],
                "customer_id": None,
                "note": None,
            },
        )
    )
    api = await make_ai_api(api_factory, provider)
    conversation_id, message = await propose(api, a.owner, provider, "sold 1")
    url = f"{AI_URL}/conversations/{conversation_id}/messages/{message['id']}/confirm"
    denied = await api.post(url, headers=a.owner, json={"payload": message["proposal"]["payload"]})
    assert denied.status_code == HTTPStatus.NOT_FOUND
    assert (await api.get(f"/api/v1/products/{foreign['id']}", headers=b.owner)).json()[
        "stock_quantity"
    ] == "50.000"
    # A payload that fails the schema is 422 with field details, not a 500.
    bad = await api.post(url, headers=a.owner, json={"payload": {"lines": [], "payments": []}})
    assert bad.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert bad.json()["error"]["code"] == "PROPOSAL_INVALID"
    # Another owner (business B) cannot see or confirm A's proposal.
    assert (
        await api.post(url, headers=b.owner, json={"payload": {}})
    ).status_code == HTTPStatus.NOT_FOUND


async def test_reject_expiry_and_roles(
    api_factory: ApiFactory, db_session: AsyncSession, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    provider = FakeProvider(
        proposal_turn(
            "propose_product",
            {
                "name": "Mkate",
                "selling_price": "60",
                "cost_price": None,
                "unit": "piece",
                "track_inventory": True,
                "opening_stock": None,
            },
        )
        + proposal_turn(
            "propose_product",
            {
                "name": "Maziwa",
                "selling_price": "65",
                "cost_price": None,
                "unit": "piece",
                "track_inventory": True,
                "opening_stock": None,
            },
        )
    )
    api = await make_ai_api(api_factory, provider)
    conversation_id, first = await propose(api, a.owner, provider, "add mkate 60")
    # Staff cannot use the copilot at all (AI-14), so they cannot confirm either.
    staff = await api.post(
        f"{AI_URL}/conversations/{conversation_id}/messages/{first['id']}/confirm",
        headers=a.staff,
        json={"payload": first["proposal"]["payload"]},
    )
    assert staff.status_code == HTTPStatus.FORBIDDEN
    rejected = await api.post(
        f"{AI_URL}/conversations/{conversation_id}/messages/{first['id']}/reject", headers=a.owner
    )
    assert (
        rejected.status_code == HTTPStatus.OK
        and rejected.json()["message"]["proposal"]["status"] == "REJECTED"
    )
    assert len(await _audits(db_session, a.business_id, "ai.proposal_reject")) == 1
    assert (await api.get("/api/v1/products", headers=a.owner)).json() == []

    second = (await ask(api, a.owner, conversation_id, "add maziwa 65")).json()["assistant_message"]
    # Age the proposal past the TTL behind the API's back.
    await db_session.execute(
        update(AIMessage)
        .where(AIMessage.id == uuid.UUID(second["id"]))
        .values(created_at=datetime.now(UTC) - timedelta(hours=25))
    )
    await db_session.flush()
    expired = await api.post(
        f"{AI_URL}/conversations/{conversation_id}/messages/{second['id']}/confirm",
        headers=a.owner,
        json={"payload": second["proposal"]["payload"]},
    )
    assert expired.status_code == HTTPStatus.CONFLICT
    assert expired.json()["error"]["code"] == "PROPOSAL_EXPIRED"


async def test_invalid_proposal_arguments_are_dropped_not_stored(
    api_factory: ApiFactory, tenants: tuple[Tenant, Tenant]
) -> None:
    """A propose call the schema rejects becomes a plain answer, never a pending action."""
    a, _ = tenants
    provider = FakeProvider(
        proposal_turn(
            "propose_product", {"name": "", "selling_price": "-5"}, "I could not prepare that."
        )
    )
    api = await make_ai_api(api_factory, provider)
    _, message = await propose(api, a.owner, provider, "add something")
    assert message["proposal"] is None and message["content"] == "I could not prepare that."
    assert message["tool_calls"][0]["name"] == "propose_product"


async def test_model_claiming_success_changes_nothing(
    api_factory: ApiFactory, tenants: tuple[Tenant, Tenant]
) -> None:
    """Whatever the model says, no record exists until the owner confirms."""
    a, _ = tenants
    provider = FakeProvider([text_response("Done! I added Sukari 1kg at KSh 160.")])
    api = await make_ai_api(api_factory, provider)
    _, message = await propose(api, a.owner, provider, "add sukari")
    assert message["proposal"] is None
    assert (await api.get("/api/v1/products", headers=a.owner)).json() == []
