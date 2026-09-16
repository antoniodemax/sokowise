"""Products (PRD FR-D1-FR-D6; docs/DATA_MAPPING.md §3.6).

Uniqueness is left to the database (partial unique indexes on active name, SKU and
barcode, all per business) and translated to stable 409 codes. A product's
category must belong to the same business: the lookup is business-scoped, so a
foreign category is "not found" (404) exactly like a nonexistent one, and the
composite FK `(category_id, business_id)` backs that up in the database.

Only the *current* state lives here. Sale lines snapshot price and cost at sale
time (BR-5), so changing a product never rewrites history.
"""

import uuid
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import BusinessContext, ClientInfo
from app.core.errors import ConflictError, NotFoundError
from app.db.session import transaction
from app.models import Product
from app.models.enums import MovementType
from app.repositories import categories as category_repo
from app.repositories import products as product_repo
from app.schemas.catalog import ProductCreateRequest, ProductUpdateRequest
from app.services import audit, inventory
from app.services.audit import AuditAction

ENTITY_TYPE = "product"

_CONFLICTS: dict[str, tuple[str, str]] = {
    "uq_products_business_id_lower_name_active": (
        "PRODUCT_NAME_EXISTS",
        "An active product with this name already exists",
    ),
    "uq_products_business_id_sku": ("SKU_EXISTS", "A product with this SKU already exists"),
    "uq_products_business_id_barcode": (
        "BARCODE_EXISTS",
        "A product with this barcode already exists",
    ),
}
_PRICE_FIELDS = ("selling_price", "cost_price")


def _translate(exc: IntegrityError) -> ConflictError | None:
    text = str(exc.orig)
    for constraint, (code, message) in _CONFLICTS.items():
        if constraint in text:
            return ConflictError(message, code=code)
    return None


async def _ensure_category(
    session: AsyncSession, ctx: BusinessContext, category_id: uuid.UUID | None
) -> None:
    """A category id must resolve within the caller's business; anything else is a 404."""
    if category_id is None:
        return
    category = await category_repo.get_category(
        session, business_id=ctx.business_id, category_id=category_id
    )
    if category is None:
        raise NotFoundError("Category not found")


async def list_products(
    session: AsyncSession,
    ctx: BusinessContext,
    *,
    query: str | None,
    category_id: uuid.UUID | None,
    include_archived: bool,
    limit: int,
) -> list[Product]:
    return await product_repo.list_products(
        session,
        ctx.business_id,
        query=query,
        category_id=category_id,
        include_archived=include_archived,
        limit=limit,
    )


async def get_product(
    session: AsyncSession, ctx: BusinessContext, product_id: uuid.UUID
) -> Product:
    product = await product_repo.get_product(
        session, business_id=ctx.business_id, product_id=product_id
    )
    if product is None:
        raise NotFoundError("Product not found")
    return product


async def create_product(
    session: AsyncSession, ctx: BusinessContext, data: ProductCreateRequest, client: ClientInfo
) -> Product:
    """Insert the product and, when `opening_stock` is given, its INITIAL movement, atomically."""
    try:
        async with transaction(session):
            await _ensure_category(session, ctx, data.category_id)
            product = Product(
                business_id=ctx.business_id,
                category_id=data.category_id,
                name=data.name,
                sku=data.sku,
                barcode=data.barcode,
                unit=data.unit,
                selling_price=data.selling_price,
                cost_price=data.cost_price,
                track_inventory=data.track_inventory,
                stock_quantity=Decimal("0"),
                low_stock_threshold=data.low_stock_threshold,
                is_active=True,
            )
            session.add(product)
            await session.flush()
            if data.opening_stock is not None:
                unit_cost = (
                    data.opening_unit_cost
                    if data.opening_unit_cost is not None
                    else data.cost_price
                )
                await inventory.apply_movement(
                    session,
                    ctx,
                    product=product,
                    movement_type=MovementType.INITIAL,
                    quantity_delta=data.opening_stock,
                    unit_cost=unit_cost,
                )
            await session.refresh(product)
    except IntegrityError as exc:
        conflict = _translate(exc)
        if conflict is not None:
            raise conflict from None
        raise
    return product


async def update_product(
    session: AsyncSession,
    ctx: BusinessContext,
    product_id: uuid.UUID,
    data: ProductUpdateRequest,
    client: ClientInfo,
) -> Product:
    try:
        async with transaction(session):
            product = await product_repo.get_product_for_update(
                session, business_id=ctx.business_id, product_id=product_id
            )
            if product is None:
                raise NotFoundError("Product not found")
            changes = {name: getattr(data, name) for name in data.model_fields_set}
            if "category_id" in changes:
                await _ensure_category(session, ctx, changes["category_id"])
            if changes.get("track_inventory") is False and product.stock_quantity != 0:
                raise ConflictError(
                    "Adjust the stock to zero before switching off stock tracking",
                    code="PRODUCT_HAS_STOCK",
                )

            price_before: dict[str, object] = {}
            price_after: dict[str, object] = {}
            lifecycle: AuditAction | None = None
            for name, value in changes.items():
                current = getattr(product, name)
                if current == value:
                    continue
                if name in _PRICE_FIELDS:
                    price_before[name] = _plain(current)
                    price_after[name] = _plain(value)
                if name == "is_active":
                    lifecycle = (
                        AuditAction.PRODUCT_UNARCHIVE if value else AuditAction.PRODUCT_ARCHIVE
                    )
                setattr(product, name, value)
            await session.flush()

            if price_after:
                await audit.record(
                    session,
                    ctx,
                    action=AuditAction.PRODUCT_PRICE_CHANGE,
                    entity_type=ENTITY_TYPE,
                    entity_id=product.id,
                    before=price_before,
                    after=price_after,
                    client=client,
                )
            if lifecycle is not None:
                await audit.record(
                    session,
                    ctx,
                    action=lifecycle,
                    entity_type=ENTITY_TYPE,
                    entity_id=product.id,
                    before={"is_active": not product.is_active},
                    after={"is_active": product.is_active},
                    client=client,
                )
            await session.refresh(product)
    except IntegrityError as exc:
        conflict = _translate(exc)
        if conflict is not None:
            raise conflict from None
        raise
    return product


def _plain(value: object) -> object:
    """JSON-safe form for audit payloads: Decimals become strings (never floats)."""
    return str(value) if isinstance(value, Decimal) else value
