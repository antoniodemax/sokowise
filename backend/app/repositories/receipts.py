"""receipts / receipt_lines (docs/DATA_MAPPING.md §3.17-§3.18). Every lookup is business-scoped."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Receipt, ReceiptLine

MAX_LIST_LIMIT = 100


async def add_receipt(session: AsyncSession, receipt: Receipt) -> Receipt:
    session.add(receipt)
    await session.flush()
    return receipt


async def get_receipt(
    session: AsyncSession,
    *,
    business_id: uuid.UUID,
    receipt_id: uuid.UUID,
    for_update: bool = False,
) -> Receipt | None:
    stmt = select(Receipt).where(Receipt.business_id == business_id, Receipt.id == receipt_id)
    if for_update:
        stmt = stmt.with_for_update()
    receipt: Receipt | None = await session.scalar(stmt)
    return receipt


async def list_receipts(
    session: AsyncSession, *, business_id: uuid.UUID, limit: int
) -> list[Receipt]:
    stmt = (
        select(Receipt)
        .where(Receipt.business_id == business_id)
        .order_by(Receipt.created_at.desc(), Receipt.id)
        .limit(min(limit, MAX_LIST_LIMIT))
    )
    return list(await session.scalars(stmt))


async def list_lines(
    session: AsyncSession, *, business_id: uuid.UUID, receipt_id: uuid.UUID
) -> list[ReceiptLine]:
    stmt = (
        select(ReceiptLine)
        .where(ReceiptLine.business_id == business_id, ReceiptLine.receipt_id == receipt_id)
        .order_by(ReceiptLine.position, ReceiptLine.id)
    )
    return list(await session.scalars(stmt))


async def count_lines(
    session: AsyncSession, *, business_id: uuid.UUID, receipt_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not receipt_ids:
        return {}
    from sqlalchemy import func

    stmt = (
        select(ReceiptLine.receipt_id, func.count())
        .where(ReceiptLine.business_id == business_id, ReceiptLine.receipt_id.in_(receipt_ids))
        .group_by(ReceiptLine.receipt_id)
    )
    return {receipt_id: int(count) for receipt_id, count in await session.execute(stmt)}


async def replace_lines(
    session: AsyncSession, *, receipt: Receipt, lines: list[ReceiptLine]
) -> None:
    """Drop any previous extraction's lines (a re-run) and insert the new ones."""
    for old in await list_lines(session, business_id=receipt.business_id, receipt_id=receipt.id):
        await session.delete(old)
    await session.flush()
    session.add_all(lines)
    await session.flush()
