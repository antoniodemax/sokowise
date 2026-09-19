"""Pasted M-Pesa confirmation SMS: parse, store, link (docs/ARCHITECTURE.md §7).

A message is a record that money arrived on the shop's line. It never moves money by
itself: a sale's MPESA tender or a credit repayment does that, and the message is
*linked* to it by the transaction code, either when the message is pasted (the code
already exists) or when the sale/repayment is recorded afterwards (the reverse hook
`link_reference_in_transaction`, called from `services.sales` and `services.credit`).

Rules (all scoped by `ctx.business_id`):
  (a) code equals a CONFIRMED MPESA tender of a COMPLETED sale  → MATCHED to the payment
  (b) code equals an MPESA credit REPAYMENT's reference         → MATCHED to the repayment
  (c) otherwise UNMATCHED, with *suggestions* (same amount close in time; customers whose
      phone ends with the sender's visible digits) that are never applied automatically.
Customer-side messages ("sent to", "paid to") are not shop income and are refused.
Unreadable text is kept as UNPARSED so unknown formats surface during the pilot.

Privacy: raw text, sender name and phone stay in the table. Logs and audit rows carry
ids, codes, amounts and statuses only.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import queries as analytics
from app.analytics.periods import period_for_dates
from app.core.context import BusinessContext, ClientInfo
from app.core.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.db.session import transaction
from app.models import Customer, MpesaMessage, Payment, Sale
from app.models.enums import MembershipRole, MoneyReceivedMethod, MpesaMessageStatus
from app.mpesa.parser import SmsDirection, parse_mpesa_sms, redact_balance
from app.repositories import mpesa as mpesa_repo
from app.schemas.credit import RepaymentRequest
from app.schemas.mpesa import MpesaIgnoreRequest, MpesaMatchRequest, MpesaRepaymentRequest
from app.services import audit
from app.services.audit import AuditAction

logger = logging.getLogger(__name__)

ENTITY_TYPE = "mpesa_message"
# How far a sale's time may sit from the SMS time to be *suggested* (never auto-linked).
MATCH_WINDOW = timedelta(minutes=120)
_UNIQUE_CODE_INDEX = "uq_mpesa_messages_business_id_code"
# Repayments recorded from a message replay on retry: the key is derived from the message.
_REPAYMENT_NAMESPACE = uuid.UUID("6f0f6c2e-6b7a-4f5b-9a3e-2c7d0b2e5a11")


class NotMoneyReceivedError(AppError):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "NOT_MONEY_RECEIVED"


class InvalidTransitionError(ConflictError):
    code = "MPESA_INVALID_TRANSITION"


@dataclass(frozen=True, slots=True)
class Candidates:
    payments: list[tuple[Payment, Sale]]
    customers: list[Customer]


@dataclass(frozen=True, slots=True)
class MessageView:
    message: MpesaMessage
    sale_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    candidates: Candidates | None


@dataclass(frozen=True, slots=True)
class Pasted:
    view: MessageView
    created: bool


@dataclass(frozen=True, slots=True)
class Reconciliation:
    date: date
    received_count: int
    received_total: Decimal
    matched_count: int
    matched_total: Decimal
    unmatched_count: int
    unmatched_total: Decimal
    ignored_count: int
    unparsed_count: int
    recorded_in_app: Decimal


async def paste(
    session: AsyncSession, ctx: BusinessContext, text: str, client: ClientInfo
) -> Pasted:
    parsed = parse_mpesa_sms(text)
    if parsed is not None and parsed.direction is SmsDirection.SENT:
        raise NotMoneyReceivedError(
            "This message is about money you sent or paid, not money received"
        )
    if parsed is None:
        async with transaction(session):
            message = await mpesa_repo.add(
                session,
                MpesaMessage(
                    business_id=ctx.business_id,
                    created_by=ctx.user_id,
                    status=MpesaMessageStatus.UNPARSED,
                    raw_text=redact_balance(text),
                ),
            )
            await _audit(session, ctx, AuditAction.MPESA_PASTE, message, client)
        await session.refresh(message)
        logger.info("mpesa message unparsed", extra=_log_extra(ctx, message))
        return Pasted(view=await view_of(session, ctx, message), created=True)

    existing = await mpesa_repo.get_by_code(session, business_id=ctx.business_id, code=parsed.code)
    if existing is not None:
        return Pasted(view=await view_of(session, ctx, existing), created=False)
    try:
        async with transaction(session):
            message = await mpesa_repo.add(
                session,
                MpesaMessage(
                    business_id=ctx.business_id,
                    created_by=ctx.user_id,
                    status=MpesaMessageStatus.UNMATCHED,
                    raw_text=redact_balance(text),
                    code=parsed.code,
                    amount=parsed.amount,
                    kind=parsed.kind,
                    sender_name=parsed.sender_name,
                    sender_phone_masked=parsed.sender_phone_masked,
                    sender_last3=parsed.sender_last3,
                    account_reference=parsed.account_reference,
                    occurred_at=parsed.occurred_at,
                ),
            )
            await _link_existing_record(session, ctx, message)
            await _audit(session, ctx, AuditAction.MPESA_PASTE, message, client)
    except IntegrityError as exc:
        if _UNIQUE_CODE_INDEX not in str(exc.orig):
            raise
        # A concurrent paste of the same code won; answer as a replay.
        existing = await mpesa_repo.get_by_code(
            session, business_id=ctx.business_id, code=parsed.code
        )
        if existing is None:  # pragma: no cover — the row that just conflicted must exist
            raise
        return Pasted(view=await view_of(session, ctx, existing), created=False)
    await session.refresh(message)
    logger.info("mpesa message pasted", extra=_log_extra(ctx, message))
    return Pasted(view=await view_of(session, ctx, message), created=True)


async def _link_existing_record(
    session: AsyncSession, ctx: BusinessContext, message: MpesaMessage
) -> None:
    """Rules (a) and (b) at paste time: the sale or repayment was recorded first."""
    if message.code is None:  # pragma: no cover — only parsed rows reach here
        return
    payment = await mpesa_repo.find_payment_by_reference(
        session, business_id=ctx.business_id, code=message.code
    )
    if payment is not None:
        _mark_matched(message, ctx, payment_id=payment.id)
        return
    repayment = await mpesa_repo.find_repayment_by_reference(
        session, business_id=ctx.business_id, code=message.code
    )
    if repayment is not None:
        _mark_matched(message, ctx, credit_transaction_id=repayment.id)


def _mark_matched(
    message: MpesaMessage,
    ctx: BusinessContext,
    *,
    payment_id: uuid.UUID | None = None,
    credit_transaction_id: uuid.UUID | None = None,
) -> None:
    message.status = MpesaMessageStatus.MATCHED
    message.payment_id = payment_id
    message.credit_transaction_id = credit_transaction_id
    message.matched_by = ctx.user_id
    message.matched_at = datetime.now(UTC)


async def get_message(
    session: AsyncSession, ctx: BusinessContext, message_id: uuid.UUID
) -> MessageView:
    message = await _get(session, ctx, message_id)
    return await view_of(session, ctx, message)


async def list_messages(
    session: AsyncSession,
    ctx: BusinessContext,
    *,
    status: MpesaMessageStatus | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
) -> list[MessageView]:
    start = end = None
    if date_from is not None and date_to is not None:
        period = period_for_dates(ctx.timezone, date_from, date_to)
        start, end = period.start, period.end
    rows = await mpesa_repo.list_messages(
        session,
        ctx.business_id,
        status=status,
        occurred_from=start,
        occurred_until=end,
        limit=limit,
    )
    return [await view_of(session, ctx, row, with_candidates=False) for row in rows]


async def match(
    session: AsyncSession,
    ctx: BusinessContext,
    message_id: uuid.UUID,
    data: MpesaMatchRequest,
    client: ClientInfo,
) -> MessageView:
    """The owner or attendant picks the record this message belongs to."""
    async with transaction(session):
        message = await _get(session, ctx, message_id, for_update=True)
        _require_status(message, MpesaMessageStatus.UNMATCHED, "matched")
        if data.payment_id is not None:
            payment = await mpesa_repo.get_unlinked_payment(
                session, business_id=ctx.business_id, payment_id=data.payment_id
            )
            if payment is None:
                raise NotFoundError("Sale payment not found")
            _mark_matched(message, ctx, payment_id=payment.id)
            after: dict[str, object] = {"payment_id": str(payment.id)}
        elif data.credit_transaction_id is not None:
            repayment = await mpesa_repo.get_unlinked_repayment(
                session,
                business_id=ctx.business_id,
                credit_transaction_id=data.credit_transaction_id,
            )
            if repayment is None:
                raise NotFoundError("Repayment not found")
            _mark_matched(message, ctx, credit_transaction_id=repayment.id)
            after = {"credit_transaction_id": str(repayment.id)}
        else:  # pragma: no cover — the schema requires exactly one target
            raise NotFoundError("Nothing to match")
        await session.flush()
        await audit.record(
            session,
            ctx,
            action=AuditAction.MPESA_MATCH,
            entity_type=ENTITY_TYPE,
            entity_id=message.id,
            after={**after, "via": "manual"},
            client=client,
        )
    await session.refresh(message)
    return await view_of(session, ctx, message)


async def record_repayment_for_message(
    session: AsyncSession,
    ctx: BusinessContext,
    message_id: uuid.UUID,
    data: MpesaRepaymentRequest,
    client: ClientInfo,
) -> MessageView:
    """Record the message's amount as a credit repayment; the reverse hook links it."""
    from app.services import credit  # local import: credit does not depend on mpesa

    message = await _get(session, ctx, message_id)
    _require_status(message, MpesaMessageStatus.UNMATCHED, "recorded as a repayment")
    if message.code is None or message.amount is None:  # pragma: no cover — UNMATCHED rows
        raise InvalidTransitionError("This message has no amount to record")
    request = RepaymentRequest(
        amount=message.amount,
        payment_method=MoneyReceivedMethod.MPESA,
        reference=message.code,
        allow_overpayment=data.allow_overpayment,
    )
    await credit.record_repayment(
        session,
        ctx,
        data.customer_id,
        request,
        client,
        idempotency_key=uuid.uuid5(_REPAYMENT_NAMESPACE, str(message.id)),
    )
    await session.refresh(message)
    return await view_of(session, ctx, message)


async def ignore(
    session: AsyncSession,
    ctx: BusinessContext,
    message_id: uuid.UUID,
    data: MpesaIgnoreRequest,
    client: ClientInfo,
) -> MessageView:
    """OWNER only: this message is not shop income (a refund, a personal transfer, noise)."""
    if ctx.role is not MembershipRole.OWNER:
        raise PermissionDeniedError("Only an owner can ignore an M-Pesa message")
    async with transaction(session):
        message = await _get(session, ctx, message_id, for_update=True)
        if message.status is MpesaMessageStatus.IGNORED:
            return await view_of(session, ctx, message)
        if message.status is MpesaMessageStatus.MATCHED:
            raise InvalidTransitionError("A matched message cannot be ignored")
        before = message.status.value
        message.status = MpesaMessageStatus.IGNORED
        message.ignored_by = ctx.user_id
        message.ignored_at = datetime.now(UTC)
        message.ignore_reason = data.reason
        await session.flush()
        await audit.record(
            session,
            ctx,
            action=AuditAction.MPESA_IGNORE,
            entity_type=ENTITY_TYPE,
            entity_id=message.id,
            before={"status": before},
            after={"status": MpesaMessageStatus.IGNORED.value, "reason": data.reason},
            client=client,
        )
    await session.refresh(message)
    return await view_of(session, ctx, message)


async def link_reference_in_transaction(
    session: AsyncSession,
    ctx: BusinessContext,
    *,
    reference: str | None,
    payment_id: uuid.UUID | None = None,
    credit_transaction_id: uuid.UUID | None = None,
    via: str,
    client: ClientInfo | None,
) -> None:
    """Reverse hook: a sale or repayment was just recorded with an M-Pesa code.

    Runs inside the caller's transaction, after its own rows are flushed, and touches at
    most one UNMATCHED message. Nothing happens when the code is unknown.
    """
    code = _normalise(reference)
    if code is None:
        return
    message = await mpesa_repo.link_by_code(
        session,
        business_id=ctx.business_id,
        code=code,
        payment_id=payment_id,
        credit_transaction_id=credit_transaction_id,
        matched_by=ctx.user_id,
        matched_at=datetime.now(UTC),
    )
    if message is None:
        return
    await audit.record(
        session,
        ctx,
        action=AuditAction.MPESA_MATCH,
        entity_type=ENTITY_TYPE,
        entity_id=message.id,
        after={
            "payment_id": str(payment_id) if payment_id else None,
            "credit_transaction_id": str(credit_transaction_id) if credit_transaction_id else None,
            "via": via,
        },
        client=client,
    )


async def unlink_payment_in_transaction(
    session: AsyncSession, ctx: BusinessContext, *, payment_id: uuid.UUID, client: ClientInfo
) -> None:
    """A sale was voided: its M-Pesa message goes back to UNMATCHED."""
    message = await mpesa_repo.unlink_payment(
        session, business_id=ctx.business_id, payment_id=payment_id
    )
    if message is None:
        return
    await audit.record(
        session,
        ctx,
        action=AuditAction.MPESA_UNLINK,
        entity_type=ENTITY_TYPE,
        entity_id=message.id,
        before={"payment_id": str(payment_id)},
        after={"status": MpesaMessageStatus.UNMATCHED.value, "via": "sale.void"},
        client=client,
    )


async def reconciliation(session: AsyncSession, ctx: BusinessContext, day: date) -> Reconciliation:
    period = period_for_dates(ctx.timezone, day, day)
    totals = await mpesa_repo.daily_totals(
        session, ctx.business_id, start=period.start, end=period.end
    )
    zero = (0, Decimal("0.00"))
    matched = totals.get(MpesaMessageStatus.MATCHED, zero)
    unmatched = totals.get(MpesaMessageStatus.UNMATCHED, zero)
    ignored = totals.get(MpesaMessageStatus.IGNORED, zero)
    unparsed = await mpesa_repo.unparsed_count(
        session, ctx.business_id, start=period.start, end=period.end
    )
    recorded = await analytics.cash_collected(session, ctx.business_id, period)
    return Reconciliation(
        date=day,
        received_count=matched[0] + unmatched[0],
        received_total=matched[1] + unmatched[1],
        matched_count=matched[0],
        matched_total=matched[1],
        unmatched_count=unmatched[0],
        unmatched_total=unmatched[1],
        ignored_count=ignored[0],
        unparsed_count=unparsed,
        recorded_in_app=recorded.get("MPESA", Decimal("0.00")),
    )


async def view_of(
    session: AsyncSession,
    ctx: BusinessContext,
    message: MpesaMessage,
    *,
    with_candidates: bool = True,
) -> MessageView:
    sale_id = customer_id = None
    if message.payment_id is not None:
        sale_id = await mpesa_repo.sale_id_of_payment(
            session, business_id=ctx.business_id, payment_id=message.payment_id
        )
    if message.credit_transaction_id is not None:
        customer_id = await mpesa_repo.customer_id_of_repayment(
            session,
            business_id=ctx.business_id,
            credit_transaction_id=message.credit_transaction_id,
        )
    candidates = None
    if (
        with_candidates
        and message.status is MpesaMessageStatus.UNMATCHED
        and message.amount is not None
        and message.occurred_at is not None
    ):
        payments = await mpesa_repo.candidate_payments(
            session,
            business_id=ctx.business_id,
            amount=message.amount,
            around=message.occurred_at,
            window=MATCH_WINDOW,
        )
        customers = (
            await mpesa_repo.candidate_customers(
                session, business_id=ctx.business_id, last3=message.sender_last3
            )
            if message.sender_last3
            else []
        )
        candidates = Candidates(payments=payments, customers=customers)
    return MessageView(
        message=message, sale_id=sale_id, customer_id=customer_id, candidates=candidates
    )


async def _get(
    session: AsyncSession, ctx: BusinessContext, message_id: uuid.UUID, *, for_update: bool = False
) -> MpesaMessage:
    message = await mpesa_repo.get_message(
        session, business_id=ctx.business_id, message_id=message_id, for_update=for_update
    )
    if message is None:
        raise NotFoundError("M-Pesa message not found")
    return message


def _require_status(message: MpesaMessage, wanted: MpesaMessageStatus, verb: str) -> None:
    if message.status is not wanted:
        raise InvalidTransitionError(f"A message in state {message.status.value} cannot be {verb}")


def _normalise(reference: str | None) -> str | None:
    if reference is None:
        return None
    code = reference.strip().upper()
    return code or None


async def _audit(
    session: AsyncSession,
    ctx: BusinessContext,
    action: AuditAction,
    message: MpesaMessage,
    client: ClientInfo,
) -> None:
    await audit.record(
        session,
        ctx,
        action=action,
        entity_type=ENTITY_TYPE,
        entity_id=message.id,
        after={
            "status": message.status.value,
            "code": message.code,
            "amount": str(message.amount) if message.amount is not None else None,
            "kind": message.kind.value if message.kind else None,
            "payment_id": str(message.payment_id) if message.payment_id else None,
            "credit_transaction_id": (
                str(message.credit_transaction_id) if message.credit_transaction_id else None
            ),
        },
        client=client,
    )


def _log_extra(ctx: BusinessContext, message: MpesaMessage) -> dict[str, object]:
    return {
        "business_id": str(ctx.business_id),
        "message_id": str(message.id),
        "status": message.status.value,
    }


__all__ = [
    "MATCH_WINDOW",
    "Candidates",
    "InvalidTransitionError",
    "MessageView",
    "NotMoneyReceivedError",
    "Pasted",
    "Reconciliation",
    "get_message",
    "ignore",
    "link_reference_in_transaction",
    "list_messages",
    "match",
    "paste",
    "reconciliation",
    "record_repayment_for_message",
    "unlink_payment_in_transaction",
    "view_of",
]
