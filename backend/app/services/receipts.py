"""Supplier receipt intelligence (docs/ARCHITECTURE.md §6.7; PRD FR-E, BR-13).

    upload → validate image → store blob → row (UPLOADED)
    process → provider (image → structured proposal) → backend validation → matching
            → READY_FOR_REVIEW (or FAILED)
    confirm → owner's final lines → services.inventory.restock_in_transaction per line,
              all inside ONE transaction → CONFIRMED

The extraction is untrusted input: it is re-validated here, matched here, and only
the owner's confirmed values ever reach the inventory ledger. Nothing in this module
writes a movement itself.
"""

import io
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from http import HTTPStatus

from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.errors import AIUnavailableError
from app.ai.receipts import (
    ExtractedLine,
    ReceiptExtraction,
    ReceiptExtractionError,
    ReceiptExtractionProvider,
)
from app.core.config import Settings
from app.core.context import BusinessContext, ClientInfo
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.session import transaction
from app.models import Product, Receipt, ReceiptLine
from app.models.enums import ReceiptLineReview, ReceiptMatchStatus, ReceiptStatus
from app.repositories import products as product_repo
from app.repositories import receipts as receipt_repo
from app.schemas.inventory import RestockRequest
from app.schemas.receipts import ReceiptConfirmRequest
from app.services import audit
from app.services.audit import AuditAction
from app.services.inventory import check_restock_permission, restock_in_transaction
from app.services.receipt_matching import match_line
from app.storage import BlobStorage, StorageError

logger = logging.getLogger(__name__)

ENTITY_TYPE = "receipt"
CENT = Decimal("0.01")
# A printed line total may differ from quantity x unit cost by rounding; anything past
# this is flagged for the reviewer (never corrected silently).
ARITHMETIC_TOLERANCE_ABS = Decimal("1.00")
ARITHMETIC_TOLERANCE_REL = Decimal("0.01")

# Formats accepted from clients and forwarded to the model. Sniffed from bytes, never
# taken from the client's Content-Type.
_MAGIC: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)
ALLOWED_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


class InvalidReceiptImageError(AppError):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "RECEIPT_IMAGE_INVALID"


class ReceiptTooLargeError(AppError):
    status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    code = "RECEIPT_TOO_LARGE"


class ReceiptAINotConfiguredError(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "RECEIPT_AI_NOT_CONFIGURED"


class ReceiptStateError(ConflictError):
    code = "RECEIPT_INVALID_STATE"


class ReceiptAlreadyConfirmedError(ConflictError):
    code = "RECEIPT_ALREADY_CONFIRMED"


class ReceiptLineError(AppError):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "RECEIPT_LINE_INVALID"


class StorageUnavailableError(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "STORAGE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ValidatedImage:
    mime_type: str
    extension: str
    width: int
    height: int


# --- image validation ------------------------------------------------------------------


def _sniff(data: bytes) -> tuple[str, str] | None:
    for magic, mime, ext in _MAGIC:
        if data.startswith(magic):
            return mime, ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def validate_image(data: bytes, settings: Settings) -> ValidatedImage:
    """Sniff the format, decode the header, bound the dimensions. Client MIME is ignored."""
    if len(data) > settings.receipt_max_bytes:
        raise ReceiptTooLargeError(
            f"The image is too large; the limit is {settings.receipt_max_bytes // (1024 * 1024)} MB"
        )
    sniffed = _sniff(data)
    if sniffed is None:
        raise InvalidReceiptImageError("Upload a JPEG, PNG or WebP photo of the receipt")
    mime, ext = sniffed
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            image_format = image.format
            # Decodes enough to catch corrupt/truncated files; a bomb trips the pixel bound.
            if width * height > settings.receipt_max_pixels:
                raise InvalidReceiptImageError("The image has too many pixels; use a smaller photo")
            image.verify()
    except InvalidReceiptImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise InvalidReceiptImageError("The file is not a readable image") from None
    if (image_format or "").upper() not in {"JPEG", "PNG", "WEBP"}:
        raise InvalidReceiptImageError("Upload a JPEG, PNG or WebP photo of the receipt")
    if min(width, height) < settings.receipt_min_side_px:
        raise InvalidReceiptImageError("The image is too small to read; take a closer photo")
    return ValidatedImage(mime, ext, width, height)


# --- lifecycle -----------------------------------------------------------------------------


async def _get(
    session: AsyncSession, ctx: BusinessContext, receipt_id: uuid.UUID, *, for_update: bool = False
) -> Receipt:
    receipt = await receipt_repo.get_receipt(
        session, business_id=ctx.business_id, receipt_id=receipt_id, for_update=for_update
    )
    if receipt is None:
        raise NotFoundError("Receipt not found")
    return receipt


async def get_receipt(
    session: AsyncSession, ctx: BusinessContext, receipt_id: uuid.UUID
) -> tuple[Receipt, list[ReceiptLine]]:
    receipt = await _get(session, ctx, receipt_id)
    lines = await receipt_repo.list_lines(
        session, business_id=ctx.business_id, receipt_id=receipt.id
    )
    return receipt, lines


async def list_receipts(
    session: AsyncSession, ctx: BusinessContext, *, limit: int
) -> tuple[list[Receipt], dict[uuid.UUID, int]]:
    receipts = await receipt_repo.list_receipts(session, business_id=ctx.business_id, limit=limit)
    counts = await receipt_repo.count_lines(
        session, business_id=ctx.business_id, receipt_ids=[r.id for r in receipts]
    )
    return receipts, counts


async def get_image(
    session: AsyncSession, ctx: BusinessContext, storage: BlobStorage, receipt_id: uuid.UUID
) -> tuple[Receipt, bytes]:
    receipt = await _get(session, ctx, receipt_id)
    try:
        return receipt, await storage.get(receipt.storage_key)
    except StorageError:
        logger.exception("receipt blob unreadable", extra={"receipt_id": str(receipt.id)})
        raise StorageUnavailableError("The receipt image could not be read right now") from None


async def upload(
    session: AsyncSession,
    ctx: BusinessContext,
    storage: BlobStorage,
    settings: Settings,
    *,
    data: bytes,
    filename: str | None,
    client: ClientInfo,
) -> Receipt:
    image = validate_image(data, settings)
    receipt_id = uuid.uuid4()
    key = f"receipts/{ctx.business_id}/{receipt_id}.{image.extension}"
    receipt = Receipt(
        id=receipt_id,
        business_id=ctx.business_id,
        created_by=ctx.user_id,
        status=ReceiptStatus.UPLOADED,
        original_filename=(filename or "")[:255] or None,
        mime_type=image.mime_type,
        size_bytes=len(data),
        storage_key=key,
    )
    async with transaction(session):
        await receipt_repo.add_receipt(session, receipt)
        try:
            await storage.put(key, data, content_type=image.mime_type)
        except StorageError:
            logger.exception("receipt blob write failed", extra={"receipt_id": str(receipt_id)})
            raise StorageUnavailableError(
                "The receipt image could not be stored right now"
            ) from None
        await audit.record(
            session,
            ctx,
            action=AuditAction.RECEIPT_UPLOAD,
            entity_type=ENTITY_TYPE,
            entity_id=receipt.id,
            after={
                "mime_type": image.mime_type,
                "size_bytes": len(data),
                "width": image.width,
                "height": image.height,
            },
            client=client,
        )
    await session.refresh(receipt)
    return receipt


def _line_warnings(line: ExtractedLine) -> list[str]:
    warnings: list[str] = []
    if line.line_total is not None:
        expected = (line.quantity * line.unit_cost).quantize(CENT)
        tolerance = max(
            ARITHMETIC_TOLERANCE_ABS, (line.line_total * ARITHMETIC_TOLERANCE_REL).quantize(CENT)
        )
        if abs(expected - line.line_total) > tolerance:
            warnings.append("line_total_mismatch")
    if line.unit_cost == 0:
        warnings.append("zero_unit_cost")
    if line.confidence is not None and line.confidence < Decimal("0.6"):
        warnings.append("low_confidence")
    return warnings


def _receipt_warnings(extraction: ReceiptExtraction) -> list[str]:
    warnings: list[str] = []
    lines_sum = sum(
        (
            (line.line_total if line.line_total is not None else line.quantity * line.unit_cost)
            for line in extraction.lines
        ),
        Decimal(0),
    ).quantize(CENT)
    for field_name, printed in (("subtotal", extraction.subtotal), ("total", extraction.total)):
        if printed is None:
            continue
        tolerance = max(
            ARITHMETIC_TOLERANCE_ABS, (printed * ARITHMETIC_TOLERANCE_REL).quantize(CENT)
        )
        if abs(lines_sum - printed) > tolerance:
            warnings.append(f"{field_name}_mismatch")
    if extraction.currency and extraction.currency.upper() != "KES":
        warnings.append("currency_not_kes")
    return warnings


async def process(
    session: AsyncSession,
    ctx: BusinessContext,
    storage: BlobStorage,
    provider: ReceiptExtractionProvider | None,
    receipt_id: uuid.UUID,
    *,
    client: ClientInfo,
) -> tuple[Receipt, list[ReceiptLine]]:
    """Run extraction for an UPLOADED (or FAILED, to retry) receipt."""
    async with transaction(session):
        receipt = await _get(session, ctx, receipt_id, for_update=True)
        if receipt.status not in (ReceiptStatus.UPLOADED, ReceiptStatus.FAILED):
            raise ReceiptStateError(
                f"A receipt in state {receipt.status.value} cannot be processed"
            )
        if provider is None:
            raise ReceiptAINotConfiguredError("Receipt reading is not set up on this server yet.")
        receipt.status = ReceiptStatus.PROCESSING
        receipt.extraction_error = None
    await session.refresh(receipt)
    try:
        image = await storage.get(receipt.storage_key)
    except StorageError:
        await _fail(session, ctx, receipt, "STORAGE_UNAVAILABLE", client)
        raise StorageUnavailableError("The receipt image could not be read right now") from None
    try:
        result = await provider.extract(image, mime_type=receipt.mime_type)
    except AIUnavailableError as exc:
        await _fail(session, ctx, receipt, exc.code, client)
        raise
    extraction = result.extraction
    if not extraction.lines:
        await _fail(
            session, ctx, receipt, "NO_LINES", client, provider=result.provider, model=result.model
        )
        raise ReceiptExtractionError(
            "No products could be read from this receipt. Try a clearer, closer photo."
        )

    products = await product_repo.list_products(
        session, ctx.business_id, include_archived=False, limit=500
    )
    lines: list[ReceiptLine] = []
    for position, line in enumerate(extraction.lines):
        match = match_line(line.product_name, line.sku, products)
        lines.append(
            ReceiptLine(
                business_id=ctx.business_id,
                receipt_id=receipt.id,
                position=position,
                extracted_name=line.product_name[:160],
                extracted_sku=line.sku[:64] if line.sku else None,
                extracted_quantity=line.quantity,
                extracted_unit_cost=line.unit_cost,
                extracted_line_total=line.line_total,
                confidence=line.confidence,
                warnings=_line_warnings(line) or None,
                match_status=match.status,
                matched_product_id=match.product_id,
                candidate_product_ids=[str(c) for c in match.candidates] or None,
                review_status=ReceiptLineReview.PENDING,
            )
        )
    async with transaction(session):
        receipt = await _get(session, ctx, receipt.id, for_update=True)
        if receipt.status is not ReceiptStatus.PROCESSING:  # cancelled meanwhile
            raise ReceiptStateError("The receipt is no longer being processed")
        receipt.supplier_name = extraction.supplier_name
        receipt.receipt_number = extraction.receipt_number
        receipt.receipt_date = extraction.receipt_date
        receipt.currency = extraction.currency.upper() if extraction.currency else None
        receipt.extracted_subtotal = extraction.subtotal
        receipt.extracted_total = extraction.total
        receipt.extraction_provider = result.provider[:40]
        receipt.extraction_model = (result.model or "")[:60] or None
        receipt.warnings = _receipt_warnings(extraction) or None
        receipt.extracted_at = datetime.now(UTC)
        receipt.status = ReceiptStatus.READY_FOR_REVIEW
        await receipt_repo.replace_lines(session, receipt=receipt, lines=lines)
        await audit.record(
            session,
            ctx,
            action=AuditAction.RECEIPT_EXTRACT,
            entity_type=ENTITY_TYPE,
            entity_id=receipt.id,
            after={
                "status": receipt.status.value,
                "provider": result.provider,
                "model": result.model,
                "lines": len(lines),
                "matched": sum(
                    1 for line in lines if line.match_status is ReceiptMatchStatus.MATCHED
                ),
                "warnings": receipt.warnings,
            },
            client=client,
        )
    # Server-side timestamps expire on commit; reload before anything reads them.
    await session.refresh(receipt)
    lines = await receipt_repo.list_lines(
        session, business_id=ctx.business_id, receipt_id=receipt.id
    )
    return receipt, lines


async def _fail(
    session: AsyncSession,
    ctx: BusinessContext,
    receipt: Receipt,
    error: str,
    client: ClientInfo,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> None:
    async with transaction(session):
        locked = await _get(session, ctx, receipt.id, for_update=True)
        locked.status = ReceiptStatus.FAILED
        locked.extraction_error = error[:255]
        if provider:
            locked.extraction_provider = provider[:40]
            locked.extraction_model = (model or "")[:60] or None
        await audit.record(
            session,
            ctx,
            action=AuditAction.RECEIPT_EXTRACT,
            entity_type=ENTITY_TYPE,
            entity_id=locked.id,
            after={"status": "FAILED", "error": error},
            client=client,
        )
    await session.refresh(receipt)


async def confirm(
    session: AsyncSession,
    ctx: BusinessContext,
    receipt_id: uuid.UUID,
    data: ReceiptConfirmRequest,
    *,
    client: ClientInfo,
) -> tuple[Receipt, list[ReceiptLine], int]:
    """Apply the owner's decisions as restocks — all of them or none.

    The receipt row is locked for the whole transaction, so a second confirmation (double
    click, retry, concurrent tab) waits and then sees CONFIRMED → 409. Products are
    locked and checked by the inventory service exactly as a manual restock would be.
    """
    check_restock_permission(ctx)
    async with transaction(session):
        receipt = await _get(session, ctx, receipt_id, for_update=True)
        if receipt.status is ReceiptStatus.CONFIRMED:
            raise ReceiptAlreadyConfirmedError("This receipt has already been confirmed")
        if receipt.status is not ReceiptStatus.READY_FOR_REVIEW:
            raise ReceiptStateError(
                f"A receipt in state {receipt.status.value} cannot be confirmed"
            )
        lines = await receipt_repo.list_lines(
            session, business_id=ctx.business_id, receipt_id=receipt.id
        )
        by_id = {line.id: line for line in lines}
        decisions = {decision.line_id: decision for decision in data.lines}
        unknown = set(decisions) - set(by_id)
        if unknown:
            raise ReceiptLineError("A confirmed line does not belong to this receipt")
        supplier = data.supplier_name or receipt.supplier_name
        reason = data.reason or f"Supplier receipt {receipt.receipt_number or str(receipt.id)[:8]}"
        movements = 0
        for line in lines:
            decision = decisions.get(line.id)
            if decision is None:
                line.review_status = ReceiptLineReview.SKIPPED
                continue
            movement = await restock_in_transaction(
                session,
                ctx,
                RestockRequest(
                    product_id=decision.product_id,
                    quantity=decision.quantity,
                    unit_cost=decision.unit_cost,
                    supplier_name=supplier,
                    reason=reason,
                    update_cost_price=decision.update_cost_price,
                ),
                client,
                extra_audit={"receipt_id": str(receipt.id), "receipt_line_id": str(line.id)},
            )
            line.review_status = ReceiptLineReview.APPLIED
            line.final_product_id = decision.product_id
            line.final_quantity = decision.quantity
            line.final_unit_cost = decision.unit_cost
            line.movement_id = movement.id
            movements += 1
        receipt.status = ReceiptStatus.CONFIRMED
        receipt.confirmed_at = datetime.now(UTC)
        receipt.confirmed_by = ctx.user_id
        if data.supplier_name:
            receipt.supplier_name = data.supplier_name
        await session.flush()
        await audit.record(
            session,
            ctx,
            action=AuditAction.RECEIPT_CONFIRM,
            entity_type=ENTITY_TYPE,
            entity_id=receipt.id,
            after={
                "movements": movements,
                "skipped": len(lines) - movements,
                "movement_ids": [str(line.movement_id) for line in lines if line.movement_id],
            },
            client=client,
        )
    await session.refresh(receipt)
    lines = await receipt_repo.list_lines(
        session, business_id=ctx.business_id, receipt_id=receipt.id
    )
    return receipt, lines, movements


async def cancel(
    session: AsyncSession, ctx: BusinessContext, receipt_id: uuid.UUID, *, client: ClientInfo
) -> Receipt:
    async with transaction(session):
        receipt = await _get(session, ctx, receipt_id, for_update=True)
        if receipt.status is ReceiptStatus.CONFIRMED:
            raise ReceiptAlreadyConfirmedError("A confirmed receipt cannot be cancelled")
        if receipt.status is ReceiptStatus.CANCELLED:
            return receipt
        before = receipt.status.value
        receipt.status = ReceiptStatus.CANCELLED
        await audit.record(
            session,
            ctx,
            action=AuditAction.RECEIPT_CANCEL,
            entity_type=ENTITY_TYPE,
            entity_id=receipt.id,
            before={"status": before},
            after={"status": "CANCELLED"},
            client=client,
        )
    await session.refresh(receipt)
    return receipt


def products_for_lines(lines: list[ReceiptLine]) -> set[uuid.UUID]:
    """Every product id a review screen needs to label (matched + candidates)."""
    ids: set[uuid.UUID] = set()
    for line in lines:
        if line.matched_product_id:
            ids.add(line.matched_product_id)
        for candidate in line.candidate_product_ids or []:
            ids.add(uuid.UUID(candidate))
    return ids


__all__ = [
    "Product",
    "cancel",
    "confirm",
    "get_image",
    "get_receipt",
    "list_receipts",
    "process",
    "products_for_lines",
    "upload",
    "validate_image",
]
