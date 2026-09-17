"""Customers (ROADMAP Phase 6; PRD FR-G1, §16).

OWNER and STAFF both read and create customers ("Create / edit customers, record
repayment" is a member permission): an attendant must be able to open a credit
account mid-sale. Search is the `q` parameter of the list, so no path segment
can collide with a customer id.
"""

import csv
import io
import uuid
from collections.abc import AsyncIterator
from http import HTTPStatus
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_info, require_member, require_owner
from app.core.context import BusinessContext, ClientInfo
from app.db.session import get_session
from app.models import CreditTransaction
from app.repositories.credit import MAX_LIST_LIMIT as LEDGER_LIMIT
from app.repositories.customers import MAX_LIST_LIMIT
from app.schemas.credit import (
    AdjustmentRequest,
    BalanceDiscrepancyOut,
    BalanceRecomputeRequest,
    BalanceRecomputeResponse,
    LedgerEntryOut,
    LedgerResponse,
    RepaymentRequest,
)
from app.schemas.customers import CustomerCreateRequest, CustomerOut
from app.services import credit as credit_service
from app.services import customers as customers_service
from app.services.credit import Posted

router = APIRouter(prefix="/customers", tags=["customers"])

MemberCtx = Annotated[BusinessContext, Depends(require_member)]
OwnerCtx = Annotated[BusinessContext, Depends(require_owner)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClientDep = Annotated[ClientInfo, Depends(get_client_info)]
# Optional client-generated UUID that makes a retried write return the original entry.
IdempotencyKey = Annotated[uuid.UUID | None, Header(alias="Idempotency-Key")]


@router.get("", response_model=list[CustomerOut])
async def list_customers(
    ctx: MemberCtx,
    session: SessionDep,
    q: Annotated[
        str | None, Query(max_length=120, description="part of the name, or a phone prefix")
    ] = None,
    include_archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = MAX_LIST_LIMIT,
) -> list[CustomerOut]:
    rows = await customers_service.list_customers(
        session,
        ctx,
        query=q.strip() if q else None,
        include_archived=include_archived,
        limit=limit,
    )
    return [CustomerOut.model_validate(row, from_attributes=True) for row in rows]


@router.post("", status_code=HTTPStatus.CREATED, response_model=CustomerOut)
async def create_customer(
    payload: CustomerCreateRequest, ctx: MemberCtx, session: SessionDep
) -> CustomerOut:
    row = await customers_service.create_customer(session, ctx, payload)
    return CustomerOut.model_validate(row, from_attributes=True)


@router.post("/recompute", response_model=BalanceRecomputeResponse)
async def recompute_balances(
    payload: BalanceRecomputeRequest, ctx: OwnerCtx, session: SessionDep, client: ClientDep
) -> BalanceRecomputeResponse:
    """Compare every cached balance with its ledger (PRD BR-7); repair when `apply`."""
    result = await credit_service.recompute_balances(
        session, ctx, apply=payload.apply, client=client
    )
    return BalanceRecomputeResponse(
        customers_checked=result.customers_checked,
        discrepancies=[
            BalanceDiscrepancyOut(
                customer_id=d.customer_id,
                cached_balance=d.cached_balance,
                ledger_balance=d.ledger_balance,
                repaired=d.repaired,
            )
            for d in result.discrepancies
        ],
        applied=result.applied,
    )


CSV_COLUMNS = ("name", "phone", "balance", "credit_limit", "status", "notes", "created_date")


@router.get("/export.csv")
async def export_csv(ctx: OwnerCtx, session: SessionDep) -> StreamingResponse:
    """Every customer (archived included), oldest first, dates in the business tz (NFR-12)."""
    tz = ZoneInfo(ctx.timezone)

    async def rows() -> AsyncIterator[bytes]:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        yield buffer.getvalue().encode("utf-8")
        async for customer in customers_service.iter_export(session, ctx):
            buffer.seek(0)
            buffer.truncate()
            writer.writerow(
                [
                    customer.name,
                    customer.phone or "",
                    str(customer.balance),
                    "" if customer.credit_limit is None else str(customer.credit_limit),
                    "active" if customer.is_active else "archived",
                    customer.notes or "",
                    customer.created_at.astimezone(tz).date().isoformat(),
                ]
            )
            yield buffer.getvalue().encode("utf-8")

    return StreamingResponse(
        rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="customers.csv"'},
    )


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: uuid.UUID, ctx: MemberCtx, session: SessionDep) -> CustomerOut:
    row = await customers_service.get_customer(session, ctx, customer_id)
    return CustomerOut.model_validate(row, from_attributes=True)


# --- credit ledger (Phase 7) -------------------------------------------------------------
#
# The debtors list is `GET /api/v1/debtors` (`api/v1/debtors.py`): routes match in
# declaration order, so `/customers/debtors` would be swallowed by `/{customer_id}`.


def _ledger_entry(entry: CreditTransaction) -> LedgerEntryOut:
    return LedgerEntryOut.model_validate(entry, from_attributes=True)


def _posted_response(response: Response, posted: Posted) -> LedgerEntryOut:
    # A replayed idempotent request answers 200 with the original entry, not 201.
    response.status_code = HTTPStatus.CREATED if posted.created else HTTPStatus.OK
    return _ledger_entry(posted.entry)


@router.get("/{customer_id}/ledger", response_model=LedgerResponse)
async def get_ledger(
    customer_id: uuid.UUID,
    ctx: MemberCtx,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=LEDGER_LIMIT)] = LEDGER_LIMIT,
) -> LedgerResponse:
    customer, entries = await credit_service.get_ledger(session, ctx, customer_id, limit=limit)
    return LedgerResponse(
        customer_id=customer.id,
        balance=customer.balance,
        credit_limit=customer.credit_limit,
        entries=[_ledger_entry(e) for e in entries],
    )


@router.post(
    "/{customer_id}/repayments", status_code=HTTPStatus.CREATED, response_model=LedgerEntryOut
)
async def record_repayment(
    customer_id: uuid.UUID,
    payload: RepaymentRequest,
    response: Response,
    ctx: MemberCtx,
    session: SessionDep,
    client: ClientDep,
    idempotency_key: IdempotencyKey = None,
) -> LedgerEntryOut:
    posted = await credit_service.record_repayment(
        session, ctx, customer_id, payload, client, idempotency_key=idempotency_key
    )
    return _posted_response(response, posted)


@router.post(
    "/{customer_id}/adjustments", status_code=HTTPStatus.CREATED, response_model=LedgerEntryOut
)
async def record_adjustment(
    customer_id: uuid.UUID,
    payload: AdjustmentRequest,
    response: Response,
    ctx: OwnerCtx,
    session: SessionDep,
    client: ClientDep,
    idempotency_key: IdempotencyKey = None,
) -> LedgerEntryOut:
    posted = await credit_service.record_adjustment(
        session, ctx, customer_id, payload, client, idempotency_key=idempotency_key
    )
    return _posted_response(response, posted)
