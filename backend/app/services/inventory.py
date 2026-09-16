"""Stock ledger primitives (docs/DATA_MAPPING.md §3.7, PRD FR-E1/E2, BR-11).

Phase 5 ships only what product creation needs: `apply_movement`, the single
place that writes an `inventory_movements` row and moves `products.stock_quantity`
with it. The inventory phase builds restock / adjust / initial endpoints on top of
it; sales and voids call it too. Invariants it enforces:

- only tracked products get movements; an untracked product is a hard error here
  (callers decide earlier whether a product participates in stock at all);
- the caller holds the product row lock (`get_product_for_update`) or owns the row
  because it was created in this transaction, so `quantity_after` is the balance in
  commit order;
- stock never goes negative (BR-4) — a movement that would is refused;
- `occurred_at` is reporting time only and may be backdated.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import BusinessContext
from app.core.errors import AppError, ConflictError
from app.models import InventoryMovement, Product
from app.models.enums import MovementType
from app.repositories import inventory as inventory_repo


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
    quantity_after = product.stock_quantity + quantity_delta
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
