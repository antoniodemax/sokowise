"""Sales (ROADMAP sales phase; PRD FR-F, §16).

Members record sales; STAFF read only their own sales from today (the service
narrows the view); OWNER reads everything and is the only one who can void or
backdate. `Idempotency-Key` is mandatory on creation (FR-F6).
"""

import csv
import io
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from http import HTTPStatus
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_client_info, require_member, require_owner
from app.api.v1.common import optional_period
from app.core.context import BusinessContext, ClientInfo
from app.db.session import get_session
from app.models import Sale
from app.repositories.sales import MAX_LIST_LIMIT
from app.schemas.sales import PaymentOut, SaleCreateRequest, SaleItemOut, SaleOut, SaleVoidRequest
from app.services import sales as sales_service

router = APIRouter(prefix="/sales", tags=["sales"])

MemberCtx = Annotated[BusinessContext, Depends(require_member)]
OwnerCtx = Annotated[BusinessContext, Depends(require_owner)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClientDep = Annotated[ClientInfo, Depends(get_client_info)]
IdempotencyKey = Annotated[uuid.UUID, Header(alias="Idempotency-Key")]


def sale_out(sale: Sale) -> SaleOut:
    return SaleOut(
        id=sale.id,
        status=sale.status,
        customer_id=sale.customer_id,
        subtotal=sale.subtotal,
        discount_amount=sale.discount_amount,
        total_amount=sale.total_amount,
        note=sale.note,
        sold_at=sale.sold_at,
        created_by=sale.created_by,
        created_at=sale.created_at,
        voided_at=sale.voided_at,
        voided_by=sale.voided_by,
        void_reason=sale.void_reason,
        items=[SaleItemOut.model_validate(i, from_attributes=True) for i in sale.items],
        payments=[PaymentOut.model_validate(p, from_attributes=True) for p in sale.payments],
    )


CSV_COLUMNS = (
    "date",
    "time",
    "sale_id",
    "status",
    "customer",
    "product",
    "quantity",
    "unit_price",
    "line_total",
    "discount_allocated",
    "net_line_total",
    "unit_cost",
    "sale_total",
    "payments",
    "note",
    "void_reason",
)


@router.get("/export.csv")
async def export_csv(
    ctx: OwnerCtx,
    session: SessionDep,
    date_from: date | None = None,
    date_to: date | None = None,
) -> StreamingResponse:
    """One row per sale line, oldest first, voided sales included with their status (NFR-12).

    Dates are the business's local calendar days; `net_line_total` is the line after its
    share of the sale-level discount (BR-14), so summing it over COMPLETED rows gives revenue.
    """
    period = optional_period(ctx, date_from, date_to)
    tz = ZoneInfo(ctx.timezone)

    async def rows() -> AsyncIterator[bytes]:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        yield buffer.getvalue().encode("utf-8")
        async for entry in sales_service.iter_export(session, ctx, period=period):
            sale = entry.sale
            local = sale.sold_at.astimezone(tz)
            payments = "; ".join(f"{p.method.value} {p.amount}" for p in sale.payments)
            buffer.seek(0)
            buffer.truncate()
            for item in sale.items:
                writer.writerow(
                    [
                        local.date().isoformat(),
                        local.strftime("%H:%M"),
                        str(sale.id),
                        sale.status.value,
                        entry.customer_name or "",
                        item.product_name,
                        str(item.quantity),
                        str(item.unit_price),
                        str(item.line_total),
                        str(item.discount_allocated),
                        str(item.line_total - item.discount_allocated),
                        "" if item.unit_cost is None else str(item.unit_cost),
                        str(sale.total_amount),
                        payments,
                        sale.note or "",
                        sale.void_reason or "",
                    ]
                )
            yield buffer.getvalue().encode("utf-8")

    suffix = f"-{period.date_from}-{period.date_to}" if period else ""
    return StreamingResponse(
        rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="sales{suffix}.csv"'},
    )


@router.get("", response_model=list[SaleOut])
async def list_sales(
    ctx: MemberCtx,
    session: SessionDep,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    customer_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 50,
) -> list[SaleOut]:
    rows = await sales_service.list_sales(
        session, ctx, date_from=date_from, date_to=date_to, customer_id=customer_id, limit=limit
    )
    return [sale_out(row) for row in rows]


@router.post("", status_code=HTTPStatus.CREATED, response_model=SaleOut)
async def create_sale(
    payload: SaleCreateRequest,
    response: Response,
    ctx: MemberCtx,
    session: SessionDep,
    client: ClientDep,
    idempotency_key: IdempotencyKey,
) -> SaleOut:
    created = await sales_service.create_sale(
        session, ctx, payload, client, idempotency_key=idempotency_key
    )
    # A replayed idempotent request answers 200 with the original sale (FR-F6).
    response.status_code = HTTPStatus.CREATED if created.created else HTTPStatus.OK
    return sale_out(created.sale)


@router.get("/{sale_id}", response_model=SaleOut)
async def get_sale(sale_id: uuid.UUID, ctx: MemberCtx, session: SessionDep) -> SaleOut:
    return sale_out(await sales_service.get_sale(session, ctx, sale_id))


@router.post("/{sale_id}/void", response_model=SaleOut)
async def void_sale(
    sale_id: uuid.UUID,
    payload: SaleVoidRequest,
    ctx: OwnerCtx,
    session: SessionDep,
    client: ClientDep,
) -> SaleOut:
    return sale_out(await sales_service.void_sale(session, ctx, sale_id, payload, client))
