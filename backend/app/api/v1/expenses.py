"""Expenses (ROADMAP analytics phase; PRD FR-H, NFR-12, §16). OWNER-only.

Dates: `date_from` / `date_to` are inclusive local calendar days in the business
timezone, exactly as in `/analytics`. Static paths (`/categories`, `/export.csv`)
are declared before `/{expense_id}` so they are never read as an id.
"""

import csv
import io
import uuid
from collections.abc import AsyncIterator
from datetime import date
from http import HTTPStatus
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import Period, period_for_dates
from app.api.deps import get_client_info, require_owner
from app.core.context import BusinessContext, ClientInfo
from app.core.errors import AppError
from app.db.session import get_session
from app.models import Expense
from app.models.enums import MoneyReceivedMethod
from app.repositories.expenses import MAX_LIST_LIMIT
from app.schemas.expenses import (
    ExpenseCategoriesOut,
    ExpenseCreateRequest,
    ExpenseOut,
    ExpenseUpdateRequest,
    normalize_category,
)
from app.services import expenses as expenses_service

router = APIRouter(prefix="/expenses", tags=["expenses"])

OwnerCtx = Annotated[BusinessContext, Depends(require_owner)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClientDep = Annotated[ClientInfo, Depends(get_client_info)]

CSV_COLUMNS = ("date", "time", "category", "amount", "payment_method", "reference", "note")


class InvalidPeriodError(AppError):
    status_code = 422
    code = "INVALID_PERIOD"


def _period(ctx: BusinessContext, date_from: date | None, date_to: date | None) -> Period | None:
    if date_from is None and date_to is None:
        return None
    if date_from is None or date_to is None:
        raise InvalidPeriodError("date_from and date_to must be given together")
    try:
        return period_for_dates(ctx.timezone, date_from, date_to)
    except ValueError as exc:
        raise InvalidPeriodError(str(exc)) from None


def _category_filter(category: str | None) -> str | None:
    return normalize_category(category) if category else None


@router.get("", response_model=list[ExpenseOut])
async def list_expenses(
    ctx: OwnerCtx,
    session: SessionDep,
    date_from: date | None = None,
    date_to: date | None = None,
    category: Annotated[str | None, Query(max_length=60)] = None,
    payment_method: MoneyReceivedMethod | None = None,
    include_deleted: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 50,
) -> list[ExpenseOut]:
    rows = await expenses_service.list_expenses(
        session,
        ctx,
        period=_period(ctx, date_from, date_to),
        category=_category_filter(category),
        payment_method=payment_method,
        include_deleted=include_deleted,
        limit=limit,
    )
    return [ExpenseOut.model_validate(row, from_attributes=True) for row in rows]


@router.post("", status_code=HTTPStatus.CREATED, response_model=ExpenseOut)
async def create_expense(
    payload: ExpenseCreateRequest, ctx: OwnerCtx, session: SessionDep, client: ClientDep
) -> ExpenseOut:
    row = await expenses_service.create_expense(session, ctx, payload, client)
    return ExpenseOut.model_validate(row, from_attributes=True)


@router.get("/categories", response_model=ExpenseCategoriesOut)
async def categories(ctx: OwnerCtx, session: SessionDep) -> ExpenseCategoriesOut:
    return ExpenseCategoriesOut(suggested=await expenses_service.suggested_categories(session, ctx))


@router.get("/export.csv")
async def export_csv(
    ctx: OwnerCtx,
    session: SessionDep,
    date_from: date | None = None,
    date_to: date | None = None,
    category: Annotated[str | None, Query(max_length=60)] = None,
    payment_method: MoneyReceivedMethod | None = None,
) -> StreamingResponse:
    """Non-deleted expenses, oldest first, dates in the business timezone (NFR-12)."""
    period = _period(ctx, date_from, date_to)
    tz = ZoneInfo(ctx.timezone)

    async def rows() -> AsyncIterator[bytes]:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        yield buffer.getvalue().encode("utf-8")
        async for expense in expenses_service.iter_export(
            session,
            ctx,
            period=period,
            category=_category_filter(category),
            payment_method=payment_method,
        ):
            buffer.seek(0)
            buffer.truncate()
            writer.writerow(_csv_row(expense, tz))
            yield buffer.getvalue().encode("utf-8")

    suffix = f"-{period.date_from}-{period.date_to}" if period else ""
    return StreamingResponse(
        rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="expenses{suffix}.csv"'},
    )


def _csv_row(expense: Expense, tz: ZoneInfo) -> list[str]:
    local = expense.incurred_at.astimezone(tz)
    return [
        local.date().isoformat(),
        local.strftime("%H:%M"),
        expense.category,
        str(expense.amount),
        expense.payment_method.value,
        expense.reference or "",
        expense.note or "",
    ]


@router.get("/{expense_id}", response_model=ExpenseOut)
async def get_expense(expense_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> ExpenseOut:
    row = await expenses_service.get_expense(session, ctx, expense_id)
    return ExpenseOut.model_validate(row, from_attributes=True)


@router.patch("/{expense_id}", response_model=ExpenseOut)
async def update_expense(
    expense_id: uuid.UUID,
    payload: ExpenseUpdateRequest,
    ctx: OwnerCtx,
    session: SessionDep,
    client: ClientDep,
) -> ExpenseOut:
    row = await expenses_service.update_expense(session, ctx, expense_id, payload, client)
    return ExpenseOut.model_validate(row, from_attributes=True)


@router.delete("/{expense_id}", status_code=HTTPStatus.NO_CONTENT)
async def delete_expense(
    expense_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep, client: ClientDep
) -> Response:
    await expenses_service.delete_expense(session, ctx, expense_id, client)
    return Response(status_code=HTTPStatus.NO_CONTENT)
