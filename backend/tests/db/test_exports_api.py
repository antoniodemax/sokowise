"""OWNER CSV exports for sales and customers (PRD NFR-12, US-17).

Same contract as the expenses export: authenticated, tenant scoped, oldest first,
deterministic, dates in the business timezone, streamed in keyset batches.
"""

import csv
import io
from http import HTTPStatus

import pytest
from app.repositories import sales as sales_repo
from httpx import AsyncClient

from tests.db.isolation import Tenant
from tests.db.sales_helpers import (
    CUSTOMERS_URL,
    SALES_URL,
    make_customer,
    make_product,
    sale_payload,
    sell,
)

pytestmark = [pytest.mark.db, pytest.mark.anyio]


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


async def test_sales_export_has_one_row_per_line_with_local_dates_and_tenders(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    sugar = await make_product(api, a.owner, name="Sugar 1kg", price="500", cost="300")
    soap = await make_product(api, a.owner, name="Soap", price="100", cost=None)
    mary = await make_customer(api, a.owner, name='Mary "Wanjiru"')
    sale = await sell(
        api,
        a.owner,
        sale_payload(
            [(sugar["id"], "2"), (soap["id"], "3")],
            [("CASH", "1000"), ("CREDIT", "200")],
            customer_id=mary["id"],
            discount_amount="100",
            note="Bulk, morning",
        ),
    )
    # Another tenant's sale must never appear.
    other = await make_product(api, b.owner, name="Other")
    await sell(api, b.owner, sale_payload([(other["id"], "1")], [("CASH", "500")]))

    response = await api.get(f"{SALES_URL}/export.csv", headers=a.owner)
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="sales.csv"' in response.headers["content-disposition"]
    rows = _rows(response.text)
    assert [r["product"] for r in rows] == ["Sugar 1kg", "Soap"]
    assert {r["sale_id"] for r in rows} == {sale["id"]}
    first, second = rows
    assert first["status"] == "COMPLETED" and first["customer"] == 'Mary "Wanjiru"'
    assert first["quantity"] == "2.000" and first["unit_price"] == "500.00"
    assert first["line_total"] == "1000.00" and first["unit_cost"] == "300.00"
    assert second["unit_cost"] == ""  # unknown cost is blank, never 0
    # The sale-level discount is allocated to the lines and reconciles to the total.
    assert first["discount_allocated"] == "76.92" and second["discount_allocated"] == "23.08"
    assert first["net_line_total"] == "923.08" and second["net_line_total"] == "276.92"
    assert first["sale_total"] == "1200.00" and first["payments"] == "CASH 1000.00; CREDIT 200.00"
    assert first["note"] == "Bulk, morning" and first["void_reason"] == ""
    assert first["date"] == sale["sold_at"][:10] or first["time"]  # local calendar day

    # Voided sales stay in the export with their status and reason.
    void = await api.post(
        f"{SALES_URL}/{sale['id']}/void", headers=a.owner, json={"reason": "typo"}
    )
    assert void.status_code == HTTPStatus.OK
    rows = _rows((await api.get(f"{SALES_URL}/export.csv", headers=a.owner)).text)
    assert {(r["status"], r["void_reason"]) for r in rows} == {("VOIDED", "typo")}


async def test_sales_export_period_filter_role_and_validation(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, _ = tenants
    assert a.staff is not None
    p = await make_product(api, a.owner)
    await sell(api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")]))
    staff = await api.get(f"{SALES_URL}/export.csv", headers=a.staff)
    assert staff.status_code == HTTPStatus.FORBIDDEN
    half = await api.get(f"{SALES_URL}/export.csv?date_from=2026-01-01", headers=a.owner)
    assert half.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert half.json()["error"]["code"] == "INVALID_PERIOD"
    past = await api.get(
        f"{SALES_URL}/export.csv?date_from=2020-01-01&date_to=2020-01-31", headers=a.owner
    )
    assert past.status_code == HTTPStatus.OK and _rows(past.text) == []
    assert 'filename="sales-2020-01-01-2020-01-31.csv"' in past.headers["content-disposition"]


async def test_sales_export_streams_more_than_one_batch(
    api: AsyncClient, tenants: tuple[Tenant, Tenant], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, _ = tenants
    monkeypatch.setattr(sales_repo, "EXPORT_BATCH", 2)
    p = await make_product(api, a.owner, stock="100")
    ids = [
        (await sell(api, a.owner, sale_payload([(p["id"], "1")], [("CASH", "500")])))["id"]
        for _ in range(5)
    ]
    rows = _rows((await api.get(f"{SALES_URL}/export.csv", headers=a.owner)).text)
    assert len(rows) == 5 and {r["sale_id"] for r in rows} == set(ids)
    assert len({r["sale_id"] for r in rows}) == 5  # keyset paging never repeats a row


async def test_customers_export_is_owner_only_tenant_scoped_and_complete(
    api: AsyncClient, tenants: tuple[Tenant, Tenant]
) -> None:
    a, b = tenants
    assert a.staff is not None
    await make_customer(api, a.owner, name="Amina", phone="+254700000201", credit_limit="2500")
    await make_customer(api, a.owner, name="Brian", notes='Pays "Fridays"')
    await make_customer(api, b.owner, name="Zed")
    assert (await api.get(f"{CUSTOMERS_URL}/export.csv", headers=a.staff)).status_code == 403
    response = await api.get(f"{CUSTOMERS_URL}/export.csv", headers=a.owner)
    assert response.status_code == HTTPStatus.OK, response.text
    rows = _rows(response.text)
    # Oldest first by created_at, then id; inside one test transaction both rows share a
    # timestamp, so only the membership is asserted here.
    assert sorted(r["name"] for r in rows) == ["Amina", "Brian"]
    amina, brian = sorted(rows, key=lambda r: r["name"])
    assert amina["phone"] == "+254700000201" and amina["credit_limit"] == "2500.00"
    assert amina["balance"] == "0.00" and amina["status"] == "active"
    assert (
        brian["phone"] == "" and brian["credit_limit"] == "" and brian["notes"] == 'Pays "Fridays"'
    )
    assert len(brian["created_date"]) == 10
