"""Sales: create, read, list, void (PRD FR-F, BR-1/3/9/14/15; DATA_MAPPING §3.9-§3.11, §6).

One transaction per sale, in this order (DATA_MAPPING §6.1):

    lock the products (FOR UPDATE, sorted by id — no deadlocks between sales)
    lock the customer if the sale names one
    validate: active products, price snapshots, totals, tenders (BR-1), credit limit
    insert sale, items (with the discount allocated, BR-14) and payments
    SALE movements through services.inventory.apply_movement (stock check + cache)
    CHARGE through services.credit.post_entry when there is a CREDIT tender
    commit

Everything the sale records is computed here from the locked rows — never from
client totals. Items snapshot name, price and cost (FR-F5), so later repricing
changes nothing. Revenue is the sale's `total_amount` (accrual); a CREDIT tender is
a receivable and never "cash collected" (BR-15).

Idempotency (FR-F6): the `Idempotency-Key` is required. Same key + same payload →
the original sale (200); same key + different payload → 409. The database unique
`(business_id, idempotency_key)` settles concurrent duplicates.
"""

import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import Period
from app.core.context import BusinessContext, ClientInfo
from app.core.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.db.session import transaction
from app.models import Customer, Payment, Product, Sale, SaleItem
from app.models.enums import (
    CreditEntryType,
    MembershipRole,
    MovementType,
    PaymentMethod,
    SaleStatus,
)
from app.repositories import customers as customer_repo
from app.repositories import inventory as inventory_repo
from app.repositories import products as product_repo
from app.repositories import sales as sales_repo
from app.schemas.business import BusinessSettings
from app.schemas.sales import SaleCreateRequest, SaleVoidRequest
from app.services import audit, credit, inventory
from app.services.audit import AuditAction
from app.services.credit import IdempotencyConflictError
from app.services.money import allocate_discount, line_total, round_money

logger = logging.getLogger(__name__)

ENTITY_TYPE = "sale"
_IDEMPOTENCY_CONSTRAINT = "uq_sales_business_id_idempotency_key"
# A sold_at slightly in the future is a clock skew, not backdating; more than this is refused.
_FUTURE_TOLERANCE = timedelta(minutes=5)


class SaleValidationError(AppError):
    """A request that is well-formed but does not add up (BR-1, FR-F4, …)."""

    status_code = 422


@dataclass(frozen=True, slots=True)
class CreatedSale:
    sale: Sale
    created: bool  # False = idempotent replay


# --- helpers -------------------------------------------------------------------------


def payload_hash(data: SaleCreateRequest) -> str:
    canonical = json.dumps(
        data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _today_start(ctx: BusinessContext) -> datetime:
    """Midnight today in the business's timezone, as an aware datetime (BR-10)."""
    now_local = datetime.now(ZoneInfo(ctx.timezone))
    return now_local.replace(hour=0, minute=0, second=0, microsecond=0)


def _staff_view(ctx: BusinessContext) -> tuple[uuid.UUID | None, datetime | None]:
    """STAFF see their own sales for today only (PRD §16); OWNER sees everything."""
    if ctx.role is MembershipRole.STAFF:
        return ctx.user_id, _today_start(ctx)
    return None, None


def _resolve_sold_at(ctx: BusinessContext, requested: datetime | None) -> datetime:
    now = datetime.now(UTC)
    if requested is None:
        return now
    if ctx.role is not MembershipRole.OWNER:
        raise PermissionDeniedError("Only an owner can backdate a sale")
    if requested > now + _FUTURE_TOLERANCE:
        raise SaleValidationError("sold_at cannot be in the future", code="SALE_IN_FUTURE")
    window_days = BusinessSettings.model_validate(ctx.settings).sale_backdate_days
    if requested < now - timedelta(days=window_days):
        raise SaleValidationError(
            f"Sales can be backdated at most {window_days} days",
            code="SALE_BACKDATE_WINDOW",
            details={"sale_backdate_days": window_days},
        )
    return min(requested, now)


async def _lock_products(
    session: AsyncSession, ctx: BusinessContext, product_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Product]:
    """FOR UPDATE on every product, in id order so concurrent sales never deadlock."""
    products: dict[uuid.UUID, Product] = {}
    for product_id in sorted(product_ids):
        product = await product_repo.get_product_for_update(
            session, business_id=ctx.business_id, product_id=product_id
        )
        if product is None:
            raise NotFoundError("Product not found")
        products[product_id] = product
    return products


async def _lock_customer(
    session: AsyncSession, ctx: BusinessContext, customer_id: uuid.UUID
) -> Customer:
    customer = await customer_repo.get_customer_for_update(
        session, business_id=ctx.business_id, customer_id=customer_id
    )
    if customer is None:
        raise NotFoundError("Customer not found")
    if not customer.is_active:
        raise ConflictError("This customer is archived", code="CUSTOMER_ARCHIVED")
    return customer


# --- create -----------------------------------------------------------------------------


async def create_sale(
    session: AsyncSession,
    ctx: BusinessContext,
    data: SaleCreateRequest,
    client: ClientInfo,
    *,
    idempotency_key: uuid.UUID,
) -> CreatedSale:
    digest = payload_hash(data)
    existing = await sales_repo.get_sale_by_idempotency_key(
        session, business_id=ctx.business_id, idempotency_key=idempotency_key
    )
    if existing is not None:
        return _replay(existing, digest)
    try:
        async with transaction(session):
            sale = await _create_sale(session, ctx, data, client, idempotency_key, digest)
    except _DuplicateAfterLockError:
        # The transaction rolled back without writing; re-read the winner in the fresh
        # transaction (the row seen under the lock belongs to the rolled-back one).
        existing = await sales_repo.get_sale_by_idempotency_key(
            session, business_id=ctx.business_id, idempotency_key=idempotency_key
        )
        if existing is None:  # pragma: no cover — it was committed a moment ago
            raise
        return _replay(existing, digest)
    except IntegrityError as exc:
        if _IDEMPOTENCY_CONSTRAINT not in str(exc.orig):
            raise
        # A concurrent request with the same key won the insert; answer as a replay.
        existing = await sales_repo.get_sale_by_idempotency_key(
            session, business_id=ctx.business_id, idempotency_key=idempotency_key
        )
        if existing is None:  # pragma: no cover — the row that just conflicted must exist
            raise
        return _replay(existing, digest)
    logger.info(
        "sale recorded",
        extra={"business_id": str(ctx.business_id), "sale_id": str(sale.id)},
    )
    return CreatedSale(sale=sale, created=True)


class _DuplicateAfterLockError(Exception):
    """Raised inside the sale transaction when the same key was committed meanwhile."""


def _replay(existing: Sale, digest: str) -> CreatedSale:
    if existing.idempotency_hash != digest:
        raise IdempotencyConflictError(
            "This Idempotency-Key was already used with a different request"
        )
    return CreatedSale(sale=existing, created=False)


async def _create_sale(
    session: AsyncSession,
    ctx: BusinessContext,
    data: SaleCreateRequest,
    client: ClientInfo,
    idempotency_key: uuid.UUID,
    digest: str,
) -> Sale:
    sold_at = _resolve_sold_at(ctx, data.sold_at)
    products = await _lock_products(session, ctx, {line.product_id for line in data.lines})
    customer = (
        await _lock_customer(session, ctx, data.customer_id)
        if data.customer_id is not None
        else None
    )
    # A concurrent duplicate that committed while we waited for the locks is a replay,
    # not a second attempt that could now fail a stock or credit-limit check (FR-F6).
    duplicate = await sales_repo.get_sale_by_idempotency_key(
        session, business_id=ctx.business_id, idempotency_key=idempotency_key
    )
    if duplicate is not None:
        raise _DuplicateAfterLockError

    # Prices and totals from the locked rows (FR-F3, FR-F5, BR-9).
    unit_prices: list[Decimal] = []
    totals: list[Decimal] = []
    for line in data.lines:
        product = products[line.product_id]
        if not product.is_active:
            raise ConflictError(
                "This product is archived and cannot be sold", code="PRODUCT_ARCHIVED"
            )
        unit_price = line.unit_price if line.unit_price is not None else product.selling_price
        unit_prices.append(unit_price)
        totals.append(line_total(line.quantity, unit_price))
    subtotal = round_money(sum(totals, Decimal("0")))
    discount = data.discount_amount.quantize(Decimal("0.01"))
    if discount > subtotal:
        raise SaleValidationError(
            "discount_amount cannot exceed the subtotal", code="DISCOUNT_EXCEEDS_SUBTOTAL"
        )
    total = subtotal - discount
    tendered = round_money(sum((p.amount for p in data.payments), Decimal("0")))
    if tendered != total:
        raise SaleValidationError(
            "Payment lines must add up to the sale total",
            code="PAYMENTS_DO_NOT_BALANCE",
            details={"total_amount": str(total), "tendered": str(tendered)},
        )
    credit_amount = round_money(
        sum((p.amount for p in data.payments if p.method is PaymentMethod.CREDIT), Decimal("0"))
    )
    if credit_amount > 0:
        assert customer is not None  # noqa: S101 — the schema requires a customer for CREDIT
        limit_check = credit.enforce_credit_limit(
            customer, credit_amount, role=ctx.role, owner_override=data.credit_limit_override
        )
    allocations = allocate_discount(discount, totals)

    sale = Sale(
        business_id=ctx.business_id,
        customer_id=customer.id if customer else None,
        idempotency_key=idempotency_key,
        idempotency_hash=digest,
        status=SaleStatus.COMPLETED,
        subtotal=subtotal,
        discount_amount=discount,
        total_amount=total,
        note=data.note,
        sold_at=sold_at,
        created_by=ctx.user_id,
    )
    session.add(sale)
    await session.flush()

    items: list[SaleItem] = []
    for line, unit_price, total_for_line, allocated in zip(
        data.lines, unit_prices, totals, allocations, strict=True
    ):
        product = products[line.product_id]
        item = SaleItem(
            business_id=ctx.business_id,
            sale_id=sale.id,
            product_id=product.id,
            product_name=product.name,
            quantity=line.quantity,
            unit_price=unit_price,
            default_unit_price=product.selling_price,
            unit_cost=product.cost_price,
            line_total=total_for_line,
            discount_allocated=allocated,
        )
        session.add(item)
        items.append(item)
    payments = [
        Payment(
            business_id=ctx.business_id,
            sale_id=sale.id,
            method=p.method,
            amount=p.amount,
            reference=p.reference,
        )
        for p in data.payments
    ]
    session.add_all(payments)
    await session.flush()

    # Stock leaves through the ledger primitive (stock check, cache, movement row).
    for item in items:
        product = products[item.product_id]
        if product.track_inventory:
            await inventory.apply_movement(
                session,
                ctx,
                product=product,
                movement_type=MovementType.SALE,
                quantity_delta=-item.quantity,
                unit_cost=item.unit_cost,
                sale_id=sale.id,
                occurred_at=sold_at,
            )

    if credit_amount > 0:
        assert customer is not None  # noqa: S101
        credit_payment = next(p for p in payments if p.method is PaymentMethod.CREDIT)
        await credit.post_entry(
            session,
            ctx,
            customer=customer,
            entry_type=CreditEntryType.CHARGE,
            amount=credit_amount,
            sale_id=sale.id,
            payment_id=credit_payment.id,
            occurred_at=sold_at,
        )
        if limit_check.exceeded:
            await audit.record(
                session,
                ctx,
                action=AuditAction.SALE_CREDIT_LIMIT_OVERRIDE,
                entity_type=ENTITY_TYPE,
                entity_id=sale.id,
                after={
                    "customer_id": str(customer.id),
                    "credit_amount": str(credit_amount),
                    "balance_before": str(limit_check.balance),
                    "credit_limit": str(limit_check.credit_limit),
                    "projected_balance": str(limit_check.projected_balance),
                },
                client=client,
            )

    await session.refresh(sale, attribute_names=["items", "payments", "created_at", "updated_at"])
    for item in sale.items:
        await session.refresh(item)
    for payment in sale.payments:
        await session.refresh(payment)
    return sale


# --- read -------------------------------------------------------------------------------


async def get_sale(session: AsyncSession, ctx: BusinessContext, sale_id: uuid.UUID) -> Sale:
    created_by, sold_from = _staff_view(ctx)
    sale = await sales_repo.get_sale(
        session,
        business_id=ctx.business_id,
        sale_id=sale_id,
        created_by=created_by,
        sold_from=sold_from,
    )
    if sale is None:
        raise NotFoundError("Sale not found")
    return sale


async def list_sales(
    session: AsyncSession,
    ctx: BusinessContext,
    *,
    date_from: datetime | None,
    date_to: datetime | None,
    customer_id: uuid.UUID | None,
    limit: int,
) -> list[Sale]:
    # A filter naming another business's customer is a cross-tenant miss (404), not [].
    if customer_id is not None and (
        await customer_repo.get_customer(
            session, business_id=ctx.business_id, customer_id=customer_id
        )
        is None
    ):
        raise NotFoundError("Customer not found")
    created_by, staff_from = _staff_view(ctx)
    sold_from = date_from
    if staff_from is not None and (sold_from is None or sold_from < staff_from):
        sold_from = staff_from
    return await sales_repo.list_sales(
        session,
        ctx.business_id,
        sold_from=sold_from,
        sold_until=date_to,
        customer_id=customer_id,
        created_by=created_by,
        limit=limit,
    )


# --- void (FR-F7, BR-3, BR-8) --------------------------------------------------------------


async def void_sale(
    session: AsyncSession,
    ctx: BusinessContext,
    sale_id: uuid.UUID,
    data: SaleVoidRequest,
    client: ClientInfo,
) -> Sale:
    """Mark the sale VOIDED and reverse its side effects; the sale row itself stays.

    Stock comes back through SALE_REVERSAL movements for every SALE movement the sale
    wrote — including products archived since (DATA_MAPPING §3.7). A CHARGE is undone
    by a REVERSAL for the full charged amount even if repayments happened, so the
    balance may go negative (BR-8).
    """
    async with transaction(session):
        sale = await sales_repo.get_sale(
            session, business_id=ctx.business_id, sale_id=sale_id, for_update=True
        )
        if sale is None:
            raise NotFoundError("Sale not found")
        if sale.status is not SaleStatus.COMPLETED:
            raise ConflictError("This sale is already voided", code="SALE_ALREADY_VOIDED")

        movements = await inventory_repo.list_movements_for_sale(
            session, business_id=ctx.business_id, sale_id=sale.id
        )
        products = await _lock_products(session, ctx, {m.product_id for m in movements})
        for movement in movements:
            if movement.movement_type is not MovementType.SALE:
                continue
            await inventory.apply_movement(
                session,
                ctx,
                product=products[movement.product_id],
                movement_type=MovementType.SALE_REVERSAL,
                quantity_delta=-movement.quantity_delta,
                unit_cost=movement.unit_cost,
                sale_id=sale.id,
            )

        charged = round_money(
            sum((p.amount for p in sale.payments if p.method is PaymentMethod.CREDIT), Decimal("0"))
        )
        if charged > 0 and sale.customer_id is not None:
            customer = await customer_repo.get_customer_for_update(
                session, business_id=ctx.business_id, customer_id=sale.customer_id
            )
            if customer is None:  # pragma: no cover — composite FK keeps this impossible
                raise NotFoundError("Customer not found")
            await credit.post_entry(
                session,
                ctx,
                customer=customer,
                entry_type=CreditEntryType.REVERSAL,
                amount=-charged,
                allow_negative=True,
                sale_id=sale.id,
                reason=data.reason,
            )

        sale.status = SaleStatus.VOIDED
        sale.voided_at = datetime.now(UTC)
        sale.voided_by = ctx.user_id
        sale.void_reason = data.reason
        await session.flush()
        await audit.record(
            session,
            ctx,
            action=AuditAction.SALE_VOID,
            entity_type=ENTITY_TYPE,
            entity_id=sale.id,
            before={"status": SaleStatus.COMPLETED.value},
            after={
                "status": SaleStatus.VOIDED.value,
                "reason": data.reason,
                "total_amount": str(sale.total_amount),
                "credit_reversed": str(charged),
            },
            client=client,
        )
        await session.refresh(sale, attribute_names=["updated_at"])
    logger.info("sale voided", extra={"business_id": str(ctx.business_id), "sale_id": str(sale.id)})
    return sale


@dataclass(frozen=True, slots=True)
class ExportSale:
    sale: Sale
    customer_name: str | None


async def iter_export(
    session: AsyncSession, ctx: BusinessContext, *, period: Period | None
) -> AsyncIterator[ExportSale]:
    """OWNER export (PRD NFR-12): every sale, voided included, oldest first, in keyset batches."""
    after: tuple[datetime, uuid.UUID] | None = None
    while True:
        batch = await sales_repo.export_batch(
            session,
            ctx.business_id,
            sold_from=period.start if period else None,
            sold_until=period.end if period else None,
            after=after,
        )
        names = await customer_repo.names_for(
            session, ctx.business_id, {s.customer_id for s in batch if s.customer_id}
        )
        for sale in batch:
            yield ExportSale(sale, names.get(sale.customer_id) if sale.customer_id else None)
        if len(batch) < sales_repo.EXPORT_BATCH:
            return
        after = (batch[-1].sold_at, batch[-1].id)
