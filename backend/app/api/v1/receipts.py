"""Supplier receipts (docs/ARCHITECTURE.md §6.7). OWNER-only: confirmation moves stock."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.receipts import ReceiptExtractionProvider
from app.api.deps import get_client_info, get_settings_dep, require_owner
from app.core.config import Settings
from app.core.context import BusinessContext, ClientInfo
from app.db.session import get_session
from app.models import Receipt, ReceiptLine
from app.repositories.receipts import MAX_LIST_LIMIT
from app.schemas.receipts import (
    ReceiptConfirmOut,
    ReceiptConfirmRequest,
    ReceiptLineOut,
    ReceiptOut,
    ReceiptSummaryOut,
)
from app.services import receipts as receipt_service
from app.services.receipts import InvalidReceiptImageError, ReceiptTooLargeError
from app.storage import BlobStorage

router = APIRouter(prefix="/receipts", tags=["receipts"])

OwnerCtx = Annotated[BusinessContext, Depends(require_owner)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ClientDep = Annotated[ClientInfo, Depends(get_client_info)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def get_storage(request: Request) -> BlobStorage:
    storage: BlobStorage = request.app.state.receipt_storage
    return storage


def get_receipt_provider(request: Request) -> ReceiptExtractionProvider | None:
    provider: ReceiptExtractionProvider | None = getattr(
        request.app.state, "receipt_provider", None
    )
    return provider


StorageDep = Annotated[BlobStorage, Depends(get_storage)]
ProviderDep = Annotated[ReceiptExtractionProvider | None, Depends(get_receipt_provider)]


def _line_out(line: ReceiptLine) -> ReceiptLineOut:
    return ReceiptLineOut(
        id=line.id,
        position=line.position,
        extracted_name=line.extracted_name,
        extracted_sku=line.extracted_sku,
        extracted_quantity=line.extracted_quantity,
        extracted_unit_cost=line.extracted_unit_cost,
        extracted_line_total=line.extracted_line_total,
        confidence=line.confidence,
        warnings=list(line.warnings or []),
        match_status=line.match_status,
        matched_product_id=line.matched_product_id,
        candidate_product_ids=[uuid.UUID(c) for c in (line.candidate_product_ids or [])],
        review_status=line.review_status,
        final_product_id=line.final_product_id,
        final_quantity=line.final_quantity,
        final_unit_cost=line.final_unit_cost,
        movement_id=line.movement_id,
    )


def _summary(receipt: Receipt, line_count: int) -> dict[str, object]:
    return {
        "id": receipt.id,
        "status": receipt.status,
        "original_filename": receipt.original_filename,
        "mime_type": receipt.mime_type,
        "size_bytes": receipt.size_bytes,
        "supplier_name": receipt.supplier_name,
        "receipt_number": receipt.receipt_number,
        "receipt_date": receipt.receipt_date,
        "currency": receipt.currency,
        "extracted_subtotal": receipt.extracted_subtotal,
        "extracted_total": receipt.extracted_total,
        "extraction_provider": receipt.extraction_provider,
        "extraction_model": receipt.extraction_model,
        "extraction_error": receipt.extraction_error,
        "warnings": list(receipt.warnings or []),
        "line_count": line_count,
        "extracted_at": receipt.extracted_at,
        "confirmed_at": receipt.confirmed_at,
        "created_at": receipt.created_at,
        "updated_at": receipt.updated_at,
    }


def receipt_out(receipt: Receipt, lines: list[ReceiptLine]) -> ReceiptOut:
    return ReceiptOut(**_summary(receipt, len(lines)), lines=[_line_out(line) for line in lines])


async def _read_upload(file: UploadFile, settings: Settings) -> bytes:
    """Read at most the limit + 1 byte; never buffer an unbounded upload."""
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(256 * 1024):
        size += len(chunk)
        if size > settings.receipt_max_bytes:
            limit_mb = settings.receipt_max_bytes // (1024 * 1024)
            raise ReceiptTooLargeError(f"The image is too large; the limit is {limit_mb} MB")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise InvalidReceiptImageError("The uploaded file is empty")
    return data


@router.post("", response_model=ReceiptOut, status_code=status.HTTP_201_CREATED)
async def upload_receipt(
    file: UploadFile,
    ctx: OwnerCtx,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
    client: ClientDep,
) -> ReceiptOut:
    data = await _read_upload(file, settings)
    receipt = await receipt_service.upload(
        session, ctx, storage, settings, data=data, filename=file.filename, client=client
    )
    return receipt_out(receipt, [])


@router.get("", response_model=list[ReceiptSummaryOut])
async def list_receipts(
    ctx: OwnerCtx,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 50,
) -> list[ReceiptSummaryOut]:
    receipts, counts = await receipt_service.list_receipts(session, ctx, limit=limit)
    return [ReceiptSummaryOut(**_summary(r, counts.get(r.id, 0))) for r in receipts]


@router.get("/{receipt_id}", response_model=ReceiptOut)
async def get_receipt(receipt_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep) -> ReceiptOut:
    receipt, lines = await receipt_service.get_receipt(session, ctx, receipt_id)
    return receipt_out(receipt, lines)


@router.get("/{receipt_id}/image")
async def get_receipt_image(
    receipt_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep, storage: StorageDep
) -> Response:
    receipt, data = await receipt_service.get_image(session, ctx, storage, receipt_id)
    return Response(
        content=data,
        media_type=receipt.mime_type,
        headers={"Cache-Control": "private, no-store", "Content-Disposition": "inline"},
    )


@router.post("/{receipt_id}/process", response_model=ReceiptOut)
async def process_receipt(
    receipt_id: uuid.UUID,
    ctx: OwnerCtx,
    session: SessionDep,
    storage: StorageDep,
    provider: ProviderDep,
    client: ClientDep,
) -> ReceiptOut:
    receipt, lines = await receipt_service.process(
        session, ctx, storage, provider, receipt_id, client=client
    )
    return receipt_out(receipt, lines)


@router.post("/{receipt_id}/confirm", response_model=ReceiptConfirmOut)
async def confirm_receipt(
    receipt_id: uuid.UUID,
    body: ReceiptConfirmRequest,
    ctx: OwnerCtx,
    session: SessionDep,
    client: ClientDep,
) -> ReceiptConfirmOut:
    receipt, lines, movements = await receipt_service.confirm(
        session, ctx, receipt_id, body, client=client
    )
    return ReceiptConfirmOut(receipt=receipt_out(receipt, lines), movements_created=movements)


@router.post("/{receipt_id}/cancel", response_model=ReceiptOut)
async def cancel_receipt(
    receipt_id: uuid.UUID, ctx: OwnerCtx, session: SessionDep, client: ClientDep
) -> ReceiptOut:
    receipt = await receipt_service.cancel(session, ctx, receipt_id, client=client)
    _, lines = await receipt_service.get_receipt(session, ctx, receipt.id)
    return receipt_out(receipt, lines)
