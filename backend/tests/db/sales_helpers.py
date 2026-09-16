"""Helpers for the sales tests."""

import uuid
from collections.abc import Sequence
from decimal import Decimal
from http import HTTPStatus
from typing import Any

from app.models import (
    AuditLog,
    CreditTransaction,
    InventoryMovement,
    Payment,
    Product,
    Sale,
    SaleItem,
)
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

SALES_URL = "/api/v1/sales"
PRODUCTS_URL = "/api/v1/products"
CUSTOMERS_URL = "/api/v1/customers"


async def make_product(
    api: AsyncClient,
    headers: dict[str, str],
    *,
    name: str = "Sugar 1kg",
    price: str = "500",
    cost: str | None = "300",
    stock: str | None = "10",
    tracked: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "selling_price": price,
        "track_inventory": tracked,
        **extra,
    }
    if cost is not None:
        payload["cost_price"] = cost
    if stock is not None:
        payload["opening_stock"] = stock
        payload["opening_unit_cost"] = cost or "0"
    response = await api.post(PRODUCTS_URL, headers=headers, json=payload)
    assert response.status_code == HTTPStatus.CREATED, response.text
    body: dict[str, Any] = response.json()
    return body


async def make_customer(
    api: AsyncClient, headers: dict[str, str], *, name: str = "Mama Njeri", **extra: Any
) -> dict[str, Any]:
    response = await api.post(CUSTOMERS_URL, headers=headers, json={"name": name, **extra})
    assert response.status_code == HTTPStatus.CREATED, response.text
    body: dict[str, Any] = response.json()
    return body


Line = tuple[str, str] | tuple[str, str, str]


def sale_payload(
    lines: Sequence[Line],
    payments: list[tuple[str, str]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """lines: (product_id, quantity[, unit_price]); payments: (method, amount)."""
    line_objs = []
    for line in lines:
        obj: dict[str, Any] = {"product_id": line[0], "quantity": line[1]}
        if len(line) == 3:
            obj["unit_price"] = line[2]
        line_objs.append(obj)
    payload: dict[str, Any] = {"lines": line_objs, **extra}
    if payments is not None:
        payload["payments"] = [{"method": m, "amount": a} for m, a in payments]
    return payload


async def post_sale(
    api: AsyncClient, headers: dict[str, str], payload: dict[str, Any], key: str | None = None
) -> Response:
    return await api.post(
        SALES_URL,
        headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
        json=payload,
    )


async def sell(
    api: AsyncClient, headers: dict[str, str], payload: dict[str, Any], key: str | None = None
) -> dict[str, Any]:
    response = await post_sale(api, headers, payload, key)
    assert response.status_code == HTTPStatus.CREATED, response.text
    body: dict[str, Any] = response.json()
    return body


async def stock_of(session: AsyncSession, product_id: str) -> Decimal:
    product = await session.get(Product, uuid.UUID(product_id))
    assert product is not None
    await session.refresh(product)
    return product.stock_quantity


async def counts(session: AsyncSession, business_id: str) -> dict[str, int]:
    bid = uuid.UUID(business_id)

    async def count(model: Any) -> int:
        return int(
            await session.scalar(
                select(func.count()).select_from(model).where(model.business_id == bid)
            )
            or 0
        )

    return {
        "sales": await count(Sale),
        "items": await count(SaleItem),
        "payments": await count(Payment),
        "movements": await count(InventoryMovement),
        "credit": await count(CreditTransaction),
        "audit": await count(AuditLog),
    }
