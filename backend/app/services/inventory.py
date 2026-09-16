"""The stock ledger (docs/DATA_MAPPING.md §3.7, PRD FR-E, BR-4, BR-6, BR-11).

`apply_movement` is the single place that writes an `inventory_movements` row and
moves `products.stock_quantity` with it; product creation (INITIAL), sales (SALE),
voids (SALE_REVERSAL) and the operations below (RESTOCK, ADJUSTMENT, INITIAL) all
go through it. Invariants it enforces:

- only tracked products get movements; an untracked product is a hard error here
  (callers decide earlier whether a product participates in stock at all);
- the caller holds the product row lock (`get_product_for_update`) or owns the row
  because it was created in this transaction, so `quantity_after` is the balance in
  commit order;
- stock never goes negative (BR-4) — a movement that would is refused;
- `occurred_at` is reporting time only and may be backdated.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import BusinessContext, ClientInfo
from app.core.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.db.session import transaction
from app.models import InventoryMovement, Product
from app.models.enums import MembershipRole, MovementType
from app.repositories import inventory as inventory_repo
from app.repositories import products as product_repo
from app.schemas.business import BusinessSettings
from app.schemas.inventory import AdjustmentRequest, InitialStockRequest, RestockRequest
from app.services import audit
from app.services.audit import AuditAction

ENTITY_TYPE = "product"


QUANTITY_STEP = Decimal("0.001")
CENT = Decimal("0.01")


class InsufficientStockError(ConflictError):
    code = "INSUFFICIENT_STOCK"


class UntrackedProductError(AppError):
    status_code = 422
    code = "PRODUCT_UNTRACKED"


async def apply_movement(
    session: AsyncSession,
    ctx: BusinessContext,
    *,
    product: Product,
    movement_type: MovementType,
    quantity_delta: Decimal,
    unit_cost: Decimal | None = None,
    reason: str | None = None,
    supplier_name: str | None = None,
    sale_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
) -> InventoryMovement:
    if product.business_id != ctx.business_id:  # pragma: no cover — repositories scope by business
        msg = "product does not belong to the business context"
        raise RuntimeError(msg)
    if not product.track_inventory:
        raise UntrackedProductError("This product does not track stock")
    quantity_delta = quantity_delta.quantize(QUANTITY_STEP)
    if unit_cost is not None:
        unit_cost = unit_cost.quantize(CENT)
    quantity_after = (product.stock_quantity + quantity_delta).quantize(QUANTITY_STEP)
    if quantity_after < 0:
        raise InsufficientStockError("Not enough stock for this movement")
    total_cost = (
        (abs(quantity_delta) * unit_cost).quantize(Decimal("0.01"))
        if unit_cost is not None
        else None
    )
    product.stock_quantity = quantity_after
    movement = InventoryMovement(
        business_id=ctx.business_id,
        product_id=product.id,
        movement_type=movement_type,
        quantity_delta=quantity_delta,
        quantity_after=quantity_after,
        unit_cost=unit_cost,
        total_cost=total_cost,
        sale_id=sale_id,
        supplier_name=supplier_name,
        reason=reason,
        occurred_at=occurred_at or datetime.now(UTC),
        created_by=ctx.user_id,
    )
    return await inventory_repo.add_movement(session, movement)


# --- operations (ROADMAP Phase 5, inventory half) ------------------------------------------


class ProductAlreadyStockedError(ConflictError):
    code = "PRODUCT_ALREADY_STOCKED"


class ProductArchivedError(ConflictError):
    code = "PRODUCT_ARCHIVED"


async def _locked_active_tracked_product(
    session: AsyncSession, ctx: BusinessContext, product_id: uuid.UUID
) -> Product:
    product = await product_repo.get_product_for_update(
        session, business_id=ctx.business_id, product_id=product_id
    )
    if product is None:
        raise NotFoundError("Product not found")
    if not product.is_active:
        raise ProductArchivedError("This product is archived")
    if not product.track_inventory:
        raise UntrackedProductError("This product does not track stock")
    return product


def _movement_payload(movement: InventoryMovement) -> dict[str, object]:
    return {
        "movement_id": str(movement.id),
        "quantity_delta": str(movement.quantity_delta),
        "quantity_after": str(movement.quantity_after),
        "unit_cost": str(movement.unit_cost) if movement.unit_cost is not None else None,
    }


async def restock(
    session: AsyncSession, ctx: BusinessContext, data: RestockRequest, client: ClientInfo
) -> InventoryMovement:
    """Stock in (an asset, never an expense — BR-6). OWNER, or STAFF when `staff_can_restock`."""
    settings = BusinessSettings.model_validate(ctx.settings)
    if ctx.role is not MembershipRole.OWNER and not settings.staff_can_restock:
        raise PermissionDeniedError("Restocking is owner-only for this business")
    async with transaction(session):
        product = await _locked_active_tracked_product(session, ctx, data.product_id)
        movement = await apply_movement(
            session,
            ctx,
            product=product,
            movement_type=MovementType.RESTOCK,
            quantity_delta=data.quantity,
            unit_cost=data.unit_cost,
            supplier_name=data.supplier_name,
            reason=data.reason,
        )
        after: dict[str, object] = _movement_payload(movement)
        new_cost = data.unit_cost.quantize(CENT)
        if data.update_cost_price and product.cost_price != new_cost:
            after["cost_price"] = {"before": _plain(product.cost_price), "after": str(new_cost)}
            product.cost_price = new_cost
            await session.flush()
        await audit.record(
            session,
            ctx,
            action=AuditAction.INVENTORY_RESTOCK,
            entity_type=ENTITY_TYPE,
            entity_id=product.id,
            after=after,
            client=client,
        )
    return movement


async def adjust(
    session: AsyncSession, ctx: BusinessContext, data: AdjustmentRequest, client: ClientInfo
) -> InventoryMovement:
    """Signed correction with a reason (BR-4); OWNER only; never below zero."""
    async with transaction(session):
        product = await _locked_active_tracked_product(session, ctx, data.product_id)
        movement = await apply_movement(
            session,
            ctx,
            product=product,
            movement_type=MovementType.ADJUSTMENT,
            quantity_delta=data.quantity_delta,
            reason=data.reason,
        )
        await audit.record(
            session,
            ctx,
            action=AuditAction.INVENTORY_ADJUST,
            entity_type=ENTITY_TYPE,
            entity_id=product.id,
            before={"stock_quantity": str(movement.quantity_after - movement.quantity_delta)},
            after={**_movement_payload(movement), "reason": data.reason},
            client=client,
        )
    return movement


async def set_initial_stock(
    session: AsyncSession, ctx: BusinessContext, data: InitialStockRequest, client: ClientInfo
) -> InventoryMovement:
    """Opening stock for a product created without it; only while it has no movements."""
    async with transaction(session):
        product = await _locked_active_tracked_product(session, ctx, data.product_id)
        existing = await inventory_repo.count_movements_for_product(
            session, business_id=ctx.business_id, product_id=product.id
        )
        if existing:
            raise ProductAlreadyStockedError(
                "This product already has stock movements; use a restock or an adjustment"
            )
        movement = await apply_movement(
            session,
            ctx,
            product=product,
            movement_type=MovementType.INITIAL,
            quantity_delta=data.quantity,
            unit_cost=data.unit_cost,
        )
        await audit.record(
            session,
            ctx,
            action=AuditAction.INVENTORY_INITIAL,
            entity_type=ENTITY_TYPE,
            entity_id=product.id,
            after=_movement_payload(movement),
            client=client,
        )
    return movement


async def list_movements(
    session: AsyncSession,
    ctx: BusinessContext,
    *,
    product_id: uuid.UUID | None,
    movement_type: MovementType | None,
    occurred_from: datetime | None,
    occurred_until: datetime | None,
    limit: int,
) -> list[InventoryMovement]:
    if product_id is not None:
        # A product of another business is "not found", never an empty history.
        product = await product_repo.get_product(
            session, business_id=ctx.business_id, product_id=product_id
        )
        if product is None:
            raise NotFoundError("Product not found")
    return await inventory_repo.list_movements(
        session,
        ctx.business_id,
        product_id=product_id,
        movement_type=movement_type,
        occurred_from=occurred_from,
        occurred_until=occurred_until,
        limit=limit,
    )


async def list_low_stock(
    session: AsyncSession, ctx: BusinessContext, *, limit: int
) -> list[tuple[Product, Decimal]]:
    settings = BusinessSettings.model_validate(ctx.settings)
    return await inventory_repo.list_low_stock(
        session,
        ctx.business_id,
        default_threshold=Decimal(settings.low_stock_default_threshold).quantize(QUANTITY_STEP),
        limit=limit,
    )


@dataclass(frozen=True, slots=True)
class StockDiscrepancy:
    product_id: uuid.UUID
    cached_stock: Decimal
    ledger_stock: Decimal
    repaired: bool


@dataclass(frozen=True, slots=True)
class RecomputeResult:
    products_checked: int
    discrepancies: list[StockDiscrepancy]
    applied: bool


async def recompute_stock(
    session: AsyncSession, ctx: BusinessContext, *, apply: bool, client: ClientInfo | None = None
) -> RecomputeResult:
    """Compare every tracked product's cache with Σ movements; rewrite it when `apply`.

    Each product is locked (`FOR UPDATE`) before its ledger total is read, so a
    concurrent movement cannot slip between the comparison and the repair. Untracked
    products are skipped (they never have movements and stay at 0). A repair writes
    no movement — it makes the cache equal the ledger, which is the truth (BR-11).
    """
    discrepancies: list[StockDiscrepancy] = []
    async with transaction(session):
        product_ids = await product_repo.list_tracked_product_ids(session, ctx.business_id)
        for product_id in product_ids:
            product = await product_repo.get_product_for_update(
                session, business_id=ctx.business_id, product_id=product_id
            )
            if product is None:  # pragma: no cover — listed a moment ago
                continue
            ledger = await inventory_repo.ledger_totals_for_product(
                session, business_id=ctx.business_id, product_id=product_id
            )
            cached = product.stock_quantity.quantize(QUANTITY_STEP)
            if cached == ledger:
                continue
            if apply:
                product.stock_quantity = ledger
                await session.flush()
                await audit.record(
                    session,
                    ctx,
                    action=AuditAction.INVENTORY_RECOMPUTE,
                    entity_type=ENTITY_TYPE,
                    entity_id=product.id,
                    before={"stock_quantity": str(cached)},
                    after={"stock_quantity": str(ledger)},
                    client=client,
                )
            discrepancies.append(
                StockDiscrepancy(
                    product_id=product_id, cached_stock=cached, ledger_stock=ledger, repaired=apply
                )
            )
    return RecomputeResult(
        products_checked=len(product_ids), discrepancies=discrepancies, applied=apply
    )


def _plain(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None
