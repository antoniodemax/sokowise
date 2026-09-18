"""M-Pesa confirmation SMS matching (docs/ARCHITECTURE.md §7).

OWNER and STAFF paste messages, match them and record repayments from them: the phone
that receives the SMS is usually at the counter. Only an OWNER can ignore a message.
"""

import uuid
from datetime import UTC, date, datetime
from http import HTTPStatus
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_info, require_member, require_owner
from app.core.context import BusinessContext, ClientInfo
from app.db.session import get_session
from app.models.enums import MpesaMessageStatus
from app.repositories.mpesa import MAX_LIST_LIMIT
from app.schemas.mpesa import (
    CandidateCustomerOut,
    CandidatePaymentOut,
    CandidatesOut,
    MpesaIgnoreRequest,
    MpesaMatchRequest,
    MpesaMessageOut,
    MpesaPasteRequest,
    MpesaRepaymentRequest,
    ReconciliationOut,
)
from app.services import mpesa as mpesa_service
from app.services.mpesa import MessageView

router = APIRouter(prefix="/mpesa", tags=["mpesa"])

MemberCtx = Annotated[BusinessContext, Depends(require_member)]
OwnerCtx = Annotated[BusinessContext, Depends(require_owner)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClientDep = Annotated[ClientInfo, Depends(get_client_info)]


def _out(view: MessageView) -> MpesaMessageOut:
    m = view.message
    candidates = None
    if view.candidates is not None:
        candidates = CandidatesOut(
            payments=[
                CandidatePaymentOut(
                    payment_id=payment.id,
                    sale_id=sale.id,
                    amount=payment.amount,
                    reference=payment.reference,
                    sold_at=sale.sold_at,
                )
                for payment, sale in view.candidates.payments
            ],
            customers=[
                CandidateCustomerOut(
                    customer_id=c.id, name=c.name, phone=c.phone, balance=c.balance
                )
                for c in view.candidates.customers
            ],
        )
    return MpesaMessageOut(
        id=m.id,
        status=m.status,
        code=m.code,
        amount=m.amount,
        kind=m.kind,
        sender_name=m.sender_name,
        sender_phone_masked=m.sender_phone_masked,
        account_reference=m.account_reference,
        occurred_at=m.occurred_at,
        raw_text=m.raw_text,
        payment_id=m.payment_id,
        sale_id=view.sale_id,
        credit_transaction_id=m.credit_transaction_id,
        customer_id=view.customer_id,
        matched_at=m.matched_at,
        ignored_at=m.ignored_at,
        ignore_reason=m.ignore_reason,
        created_at=m.created_at,
        candidates=candidates,
    )


@router.post("/messages", response_model=MpesaMessageOut)
async def paste_message(
    payload: MpesaPasteRequest,
    ctx: MemberCtx,
    session: SessionDep,
    client: ClientDep,
    response: Response,
) -> MpesaMessageOut:
    """201 when stored; 200 with the existing row when this code was pasted before."""
    pasted = await mpesa_service.paste(session, ctx, payload.text, client)
    response.status_code = HTTPStatus.CREATED if pasted.created else HTTPStatus.OK
    return _out(pasted.view)


@router.get("/messages", response_model=list[MpesaMessageOut])
async def list_messages(
    ctx: MemberCtx,
    session: SessionDep,
    status: MpesaMessageStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 100,
) -> list[MpesaMessageOut]:
    views = await mpesa_service.list_messages(
        session, ctx, status=status, date_from=date_from, date_to=date_to, limit=limit
    )
    return [_out(v) for v in views]


@router.get("/reconciliation", response_model=ReconciliationOut)
async def reconciliation(
    ctx: MemberCtx, session: SessionDep, day: Annotated[date | None, Query(alias="date")] = None
) -> ReconciliationOut:
    """Money that arrived on M-Pesa versus what the app recorded, for one local day."""
    target = day or datetime.now(UTC).astimezone(ZoneInfo(ctx.timezone)).date()
    result = await mpesa_service.reconciliation(session, ctx, target)
    return ReconciliationOut(
        date=result.date,
        received_count=result.received_count,
        received_total=result.received_total,
        matched_count=result.matched_count,
        matched_total=result.matched_total,
        unmatched_count=result.unmatched_count,
        unmatched_total=result.unmatched_total,
        ignored_count=result.ignored_count,
        unparsed_count=result.unparsed_count,
        recorded_in_app=result.recorded_in_app,
    )


@router.get("/messages/{message_id}", response_model=MpesaMessageOut)
async def get_message(
    message_id: uuid.UUID, ctx: MemberCtx, session: SessionDep
) -> MpesaMessageOut:
    return _out(await mpesa_service.get_message(session, ctx, message_id))


@router.post("/messages/{message_id}/match", response_model=MpesaMessageOut)
async def match_message(
    message_id: uuid.UUID,
    payload: MpesaMatchRequest,
    ctx: MemberCtx,
    session: SessionDep,
    client: ClientDep,
) -> MpesaMessageOut:
    return _out(await mpesa_service.match(session, ctx, message_id, payload, client))


@router.post("/messages/{message_id}/repayment", response_model=MpesaMessageOut)
async def record_repayment(
    message_id: uuid.UUID,
    payload: MpesaRepaymentRequest,
    ctx: MemberCtx,
    session: SessionDep,
    client: ClientDep,
) -> MpesaMessageOut:
    """Record the message's amount as a credit repayment for the customer, then link it."""
    return _out(
        await mpesa_service.record_repayment_for_message(session, ctx, message_id, payload, client)
    )


@router.post("/messages/{message_id}/ignore", response_model=MpesaMessageOut)
async def ignore_message(
    message_id: uuid.UUID,
    payload: MpesaIgnoreRequest,
    ctx: OwnerCtx,
    session: SessionDep,
    client: ClientDep,
) -> MpesaMessageOut:
    return _out(await mpesa_service.ignore(session, ctx, message_id, payload, client))
