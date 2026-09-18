"""mpesa_messages reads and writes, all scoped by business_id (docs/DATA_MAPPING.md §3.19)."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models import CreditTransaction, Customer, MpesaMessage, Payment, Sale
from app.models.enums import (
    CreditEntryType,
    MoneyReceivedMethod,
    MpesaMessageStatus,
    PaymentMethod,
    PaymentStatus,
    SaleStatus,
)

MAX_LIST_LIMIT = 200
MAX_CANDIDATES = 5


def _code_of(column: InstrumentedAttribute[str | None]) -> ColumnElement[str]:
    """A stored reference compared the way codes are stored: upper-cased and trimmed."""
    return func.upper(func.trim(column))


async def add(session: AsyncSession, message: MpesaMessage) -> MpesaMessage:
    session.add(message)
    await session.flush()
    return message


async def get_message(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    message_id: uuid.UUID,
    for_update: bool = False,
) -> MpesaMessage | None:
    stmt = select(MpesaMessage).where(
        MpesaMessage.business_id == business_id, MpesaMessage.id == message_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).one_or_none()


async def get_by_code(
    session: AsyncSession, *, business_id: uuid.UUID, code: str
) -> MpesaMessage | None:
    return (
        await session.scalars(
            select(MpesaMessage).where(
                MpesaMessage.business_id == business_id, MpesaMessage.code == code
            )
        )
    ).one_or_none()


async def list_messages(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    status: MpesaMessageStatus | None = None,
    occurred_from: datetime | None = None,
    occurred_until: datetime | None = None,
    limit: int = MAX_LIST_LIMIT,
) -> list[MpesaMessage]:
    """Newest first by the time on the SMS (unparsed rows by when they were pasted)."""
    when = func.coalesce(MpesaMessage.occurred_at, MpesaMessage.created_at)
    stmt = select(MpesaMessage).where(MpesaMessage.business_id == business_id)
    if status is not None:
        stmt = stmt.where(MpesaMessage.status == status)
    if occurred_from is not None:
        stmt = stmt.where(when >= occurred_from)
    if occurred_until is not None:
        stmt = stmt.where(when < occurred_until)
    stmt = stmt.order_by(when.desc(), MpesaMessage.id.desc()).limit(min(limit, MAX_LIST_LIMIT))
    return list(await session.scalars(stmt))


def _unlinked_payments(business_id: uuid.UUID) -> Select[tuple[Payment]]:
    """CONFIRMED M-Pesa tenders of COMPLETED sales that no message links to yet."""
    linked = exists().where(
        MpesaMessage.business_id == business_id, MpesaMessage.payment_id == Payment.id
    )
    return (
        select(Payment)
        .join(Sale, Sale.id == Payment.sale_id)
        .where(
            Payment.business_id == business_id,
            Payment.method == PaymentMethod.MPESA,
            Payment.status == PaymentStatus.CONFIRMED,
            Sale.status == SaleStatus.COMPLETED,
            ~linked,
        )
    )


async def find_payment_by_reference(
    session: AsyncSession, *, business_id: uuid.UUID, code: str
) -> Payment | None:
    stmt = (
        _unlinked_payments(business_id)
        .where(_code_of(Payment.reference) == code)
        .order_by(Payment.created_at)
        .limit(1)
    )
    return (await session.scalars(stmt)).first()


async def find_repayment_by_reference(
    session: AsyncSession, *, business_id: uuid.UUID, code: str
) -> CreditTransaction | None:
    linked = exists().where(
        MpesaMessage.business_id == business_id,
        MpesaMessage.credit_transaction_id == CreditTransaction.id,
    )
    stmt = (
        select(CreditTransaction)
        .where(
            CreditTransaction.business_id == business_id,
            CreditTransaction.entry_type == CreditEntryType.REPAYMENT,
            CreditTransaction.payment_method == MoneyReceivedMethod.MPESA,
            _code_of(CreditTransaction.reference) == code,
            ~linked,
        )
        .order_by(CreditTransaction.created_at)
        .limit(1)
    )
    return (await session.scalars(stmt)).first()


async def get_unlinked_payment(
    session: AsyncSession, *, business_id: uuid.UUID, payment_id: uuid.UUID
) -> Payment | None:
    return (
        await session.scalars(_unlinked_payments(business_id).where(Payment.id == payment_id))
    ).one_or_none()


async def get_unlinked_repayment(
    session: AsyncSession, *, business_id: uuid.UUID, credit_transaction_id: uuid.UUID
) -> CreditTransaction | None:
    linked = exists().where(
        MpesaMessage.business_id == business_id,
        MpesaMessage.credit_transaction_id == CreditTransaction.id,
    )
    return (
        await session.scalars(
            select(CreditTransaction).where(
                CreditTransaction.business_id == business_id,
                CreditTransaction.id == credit_transaction_id,
                CreditTransaction.entry_type == CreditEntryType.REPAYMENT,
                CreditTransaction.payment_method == MoneyReceivedMethod.MPESA,
                ~linked,
            )
        )
    ).one_or_none()


async def candidate_payments(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    amount: Decimal,
    around: datetime,
    window: timedelta,
    limit: int = MAX_CANDIDATES,
) -> list[tuple[Payment, Sale]]:
    """Same amount, sold within the window, and not already carrying some message's code."""
    known_codes = select(MpesaMessage.code).where(
        MpesaMessage.business_id == business_id, MpesaMessage.code.is_not(None)
    )
    distance = func.abs(func.extract("epoch", Sale.sold_at - around))
    stmt = (
        select(Payment, Sale)
        .join(Sale, Sale.id == Payment.sale_id)
        .where(
            Payment.business_id == business_id,
            Payment.method == PaymentMethod.MPESA,
            Payment.status == PaymentStatus.CONFIRMED,
            Sale.status == SaleStatus.COMPLETED,
            Payment.amount == amount,
            Sale.sold_at >= around - window,
            Sale.sold_at <= around + window,
            (Payment.reference.is_(None)) | (~_code_of(Payment.reference).in_(known_codes)),
            ~exists().where(
                MpesaMessage.business_id == business_id, MpesaMessage.payment_id == Payment.id
            ),
        )
        .order_by(distance, Sale.id)
        .limit(limit)
    )
    return [(row.Payment, row.Sale) for row in await session.execute(stmt)]


async def candidate_customers(
    session: AsyncSession, *, business_id: uuid.UUID, last3: str, limit: int = MAX_CANDIDATES
) -> list[Customer]:
    if not last3.isdigit():
        return []
    stmt = (
        select(Customer)
        .where(
            Customer.business_id == business_id,
            Customer.is_active.is_(True),
            Customer.phone.like("%" + last3),
        )
        .order_by(Customer.balance.desc(), func.lower(Customer.name))
        .limit(limit)
    )
    return list(await session.scalars(stmt))


async def link_by_code(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    code: str,
    payment_id: uuid.UUID | None,
    credit_transaction_id: uuid.UUID | None,
    matched_by: uuid.UUID,
    matched_at: datetime,
) -> MpesaMessage | None:
    """Link the UNMATCHED message carrying `code`, if any. Returns the linked row."""
    stmt = (
        update(MpesaMessage)
        .where(
            MpesaMessage.business_id == business_id,
            MpesaMessage.code == code,
            MpesaMessage.status == MpesaMessageStatus.UNMATCHED,
        )
        .values(
            status=MpesaMessageStatus.MATCHED,
            payment_id=payment_id,
            credit_transaction_id=credit_transaction_id,
            matched_by=matched_by,
            matched_at=matched_at,
        )
        .returning(MpesaMessage)
        .execution_options(synchronize_session="fetch")
    )
    return (await session.scalars(stmt)).one_or_none()


async def unlink_payment(
    session: AsyncSession, *, business_id: uuid.UUID, payment_id: uuid.UUID
) -> MpesaMessage | None:
    stmt = (
        update(MpesaMessage)
        .where(
            MpesaMessage.business_id == business_id,
            MpesaMessage.payment_id == payment_id,
            MpesaMessage.status == MpesaMessageStatus.MATCHED,
        )
        .values(
            status=MpesaMessageStatus.UNMATCHED,
            payment_id=None,
            matched_by=None,
            matched_at=None,
        )
        .returning(MpesaMessage)
        .execution_options(synchronize_session="fetch")
    )
    return (await session.scalars(stmt)).one_or_none()


async def daily_totals(
    session: AsyncSession, business_id: uuid.UUID, *, start: datetime, end: datetime
) -> dict[MpesaMessageStatus, tuple[int, Decimal]]:
    """(count, sum) per status for messages whose SMS time falls in [start, end)."""
    rows = await session.execute(
        select(
            MpesaMessage.status,
            func.count(),
            func.coalesce(func.sum(MpesaMessage.amount), 0),
        )
        .where(
            MpesaMessage.business_id == business_id,
            MpesaMessage.occurred_at >= start,
            MpesaMessage.occurred_at < end,
        )
        .group_by(MpesaMessage.status)
    )
    return {
        MpesaMessageStatus(status): (int(count), Decimal(total).quantize(Decimal("0.01")))
        for status, count, total in rows
    }


async def unparsed_count(
    session: AsyncSession, business_id: uuid.UUID, *, start: datetime, end: datetime
) -> int:
    """Unparsed rows have no SMS time; count them by when they were pasted."""
    count = await session.scalar(
        select(func.count())
        .select_from(MpesaMessage)
        .where(
            MpesaMessage.business_id == business_id,
            MpesaMessage.status == MpesaMessageStatus.UNPARSED,
            MpesaMessage.created_at >= start,
            MpesaMessage.created_at < end,
        )
    )
    return int(count or 0)


async def sale_id_of_payment(
    session: AsyncSession, *, business_id: uuid.UUID, payment_id: uuid.UUID
) -> uuid.UUID | None:
    result = await session.scalar(
        select(Payment.sale_id).where(Payment.business_id == business_id, Payment.id == payment_id)
    )
    return uuid.UUID(str(result)) if result is not None else None


async def customer_id_of_repayment(
    session: AsyncSession, *, business_id: uuid.UUID, credit_transaction_id: uuid.UUID
) -> uuid.UUID | None:
    result = await session.scalar(
        select(CreditTransaction.customer_id).where(
            CreditTransaction.business_id == business_id,
            CreditTransaction.id == credit_transaction_id,
        )
    )
    return uuid.UUID(str(result)) if result is not None else None
