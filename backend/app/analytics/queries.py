"""SQL aggregates for the analytics API (PRD FR-I1-FR-I5, BR-14, BR-15, BR-16).

Every function takes `business_id` from the verified context and a `Period`
(UTC bounds computed in the business timezone). Money comes back as Decimal
from NUMERIC; nothing here touches float. All figures use COMPLETED sales by
`sold_at`; voided sales never count.

Definitions (FR-I1):
    revenue        Σ sales.total_amount                      (accrual; credit included)
    discounts      Σ sales.discount_amount
    cogs           Σ sale_items.quantity x unit_cost         (lines with a known cost)
    gross_profit   revenue - cogs
    cash_collected CONFIRMED CASH/MPESA tenders of those sales + credit REPAYMENTs
                   with occurred_at in the period, by method; CREDIT tenders excluded
    tender_split   Σ payments.amount by method (CASH, MPESA, CREDIT)
    expenses       Σ non-deleted expenses with incurred_at in the period (below gross profit;
                   never subtracted from revenue)
    net_profit     gross_profit - expenses                   (FR-I1's term)
Lines with unknown cost contribute 0 to COGS and are reported as
`lines_missing_cost` / `products_missing_cost` (BR-16). Product revenue is
`line_total - discount_allocated` (BR-14), so Σ product profit = period profit.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import Date, case, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement

from app.analytics.periods import Granularity, Period
from app.models import (
    Category,
    CreditTransaction,
    Customer,
    Expense,
    Payment,
    Product,
    Sale,
    SaleItem,
)
from app.models.enums import (
    CreditEntryType,
    MoneyReceivedMethod,
    PaymentMethod,
    PaymentStatus,
    SaleStatus,
)
from app.repositories import expenses as expense_repo
from app.services.money import round_money

ZERO = Decimal("0.00")
MAX_ROWS = 200

ProductSort = Literal["quantity", "revenue", "profit"]


def _money(value: object) -> Decimal:
    return round_money(Decimal(str(value))) if value is not None else ZERO


def _quantity(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001")) if value is not None else Decimal("0")


def _completed_sales_in(business_id: uuid.UUID, period: Period) -> list[ColumnElement[bool]]:
    return [
        Sale.business_id == business_id,
        Sale.status == SaleStatus.COMPLETED,
        Sale.sold_at >= period.start,
        Sale.sold_at < period.end,
    ]


_COGS_LINE = SaleItem.quantity * SaleItem.unit_cost
_LINE_REVENUE = SaleItem.line_total - SaleItem.discount_allocated


# --- summary --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostFigures:
    cogs: Decimal
    lines_missing_cost: int
    products_missing_cost: int


@dataclass(frozen=True, slots=True)
class Summary:
    sales_count: int
    revenue: Decimal
    discounts: Decimal
    cogs: Decimal
    lines_missing_cost: int
    products_missing_cost: int
    gross_profit: Decimal
    expenses: Decimal
    net_profit: Decimal
    tender_split: dict[str, Decimal]
    cash_collected: dict[str, Decimal]
    cash_collected_total: Decimal
    receivables_outstanding: Decimal


async def _sales_totals(
    session: AsyncSession, business_id: uuid.UUID, period: Period
) -> tuple[int, Decimal, Decimal]:
    row = (
        await session.execute(
            select(
                func.count(Sale.id), func.sum(Sale.total_amount), func.sum(Sale.discount_amount)
            ).where(*_completed_sales_in(business_id, period))
        )
    ).one()
    return int(row[0] or 0), _money(row[1]), _money(row[2])


async def _cost_figures(
    session: AsyncSession, business_id: uuid.UUID, period: Period
) -> CostFigures:
    row = (
        await session.execute(
            select(
                func.sum(_COGS_LINE),
                func.count(case((SaleItem.unit_cost.is_(None), 1))),
                func.count(
                    func.distinct(case((SaleItem.unit_cost.is_(None), SaleItem.product_id)))
                ),
            )
            .select_from(SaleItem)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .where(SaleItem.business_id == business_id, *_completed_sales_in(business_id, period))
        )
    ).one()
    return CostFigures(
        cogs=_money(row[0]),
        lines_missing_cost=int(row[1] or 0),
        products_missing_cost=int(row[2] or 0),
    )


async def _tender_split(
    session: AsyncSession, business_id: uuid.UUID, period: Period
) -> dict[str, Decimal]:
    rows = await session.execute(
        select(Payment.method, func.sum(Payment.amount))
        .join(Sale, Sale.id == Payment.sale_id)
        .where(Payment.business_id == business_id, *_completed_sales_in(business_id, period))
        .group_by(Payment.method)
    )
    split = {method.value: ZERO for method in PaymentMethod}
    for method, total in rows:
        split[method.value] = _money(total)
    return split


async def _cash_collected(
    session: AsyncSession, business_id: uuid.UUID, period: Period
) -> dict[str, Decimal]:
    """CONFIRMED CASH/MPESA tenders of period sales + REPAYMENTs occurred in the period."""
    tenders = await session.execute(
        select(Payment.method, func.sum(Payment.amount))
        .join(Sale, Sale.id == Payment.sale_id)
        .where(
            Payment.business_id == business_id,
            Payment.status == PaymentStatus.CONFIRMED,
            Payment.method != PaymentMethod.CREDIT,
            *_completed_sales_in(business_id, period),
        )
        .group_by(Payment.method)
    )
    repayments = await session.execute(
        select(CreditTransaction.payment_method, func.sum(-CreditTransaction.amount))
        .where(
            CreditTransaction.business_id == business_id,
            CreditTransaction.entry_type == CreditEntryType.REPAYMENT,
            CreditTransaction.occurred_at >= period.start,
            CreditTransaction.occurred_at < period.end,
        )
        .group_by(CreditTransaction.payment_method)
    )
    collected = {"CASH": ZERO, "MPESA": ZERO}
    for method, total in tenders:
        collected[method.value] = collected.get(method.value, ZERO) + _money(total)
    for method, total in repayments:
        if method is not None:
            collected[method.value] = collected.get(method.value, ZERO) + _money(total)
    return collected


async def _expenses(session: AsyncSession, business_id: uuid.UUID, period: Period) -> Decimal:
    total = await session.scalar(
        select(func.sum(Expense.amount)).where(
            Expense.business_id == business_id,
            Expense.deleted_at.is_(None),
            Expense.incurred_at >= period.start,
            Expense.incurred_at < period.end,
        )
    )
    return _money(total)


async def _receivables(session: AsyncSession, business_id: uuid.UUID) -> Decimal:
    total = await session.scalar(
        select(func.sum(Customer.balance)).where(
            Customer.business_id == business_id, Customer.balance > 0
        )
    )
    return _money(total)


async def summary(session: AsyncSession, business_id: uuid.UUID, period: Period) -> Summary:
    sales_count, revenue, discounts = await _sales_totals(session, business_id, period)
    costs = await _cost_figures(session, business_id, period)
    tender_split = await _tender_split(session, business_id, period)
    cash = await _cash_collected(session, business_id, period)
    expenses = await _expenses(session, business_id, period)
    gross_profit = revenue - costs.cogs
    return Summary(
        sales_count=sales_count,
        revenue=revenue,
        discounts=discounts,
        cogs=costs.cogs,
        lines_missing_cost=costs.lines_missing_cost,
        products_missing_cost=costs.products_missing_cost,
        gross_profit=gross_profit,
        expenses=expenses,
        net_profit=gross_profit - expenses,
        tender_split=tender_split,
        cash_collected=cash,
        cash_collected_total=sum(cash.values(), ZERO),
        receivables_outstanding=await _receivables(session, business_id),
    )


# --- time series ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Bucket:
    bucket_start: date  # local date the bucket starts on (day / Monday / 1st)
    sales_count: int
    revenue: Decimal
    discounts: Decimal
    cogs: Decimal
    lines_missing_cost: int
    gross_profit: Decimal
    cash_collected: Decimal
    expenses: Decimal
    net_profit: Decimal


def _bucket_expr(
    column: InstrumentedAttribute[datetime], granularity: Granularity, timezone: str
) -> ColumnElement[date]:
    local = func.timezone(timezone, column)  # sold_at AT TIME ZONE tz → local wall time
    return cast(func.date_trunc(granularity.value, local), Date)


async def timeseries(
    session: AsyncSession, business_id: uuid.UUID, period: Period, granularity: Granularity
) -> list[Bucket]:
    sale_bucket = _bucket_expr(Sale.sold_at, granularity, period.timezone).label("bucket")
    sales_rows = await session.execute(
        select(
            sale_bucket,
            func.count(Sale.id),
            func.sum(Sale.total_amount),
            func.sum(Sale.discount_amount),
        )
        .where(*_completed_sales_in(business_id, period))
        .group_by(sale_bucket)
    )
    buckets: dict[date, tuple[int, Decimal, Decimal]] = {}
    for bucket, count, revenue, discounts in sales_rows:
        buckets[bucket] = (int(count), _money(revenue), _money(discounts))

    cost_rows = await session.execute(
        select(
            sale_bucket, func.sum(_COGS_LINE), func.count(case((SaleItem.unit_cost.is_(None), 1)))
        )
        .select_from(SaleItem)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(SaleItem.business_id == business_id, *_completed_sales_in(business_id, period))
        .group_by(sale_bucket)
    )
    costs = {bucket: (_money(cogs), int(missing)) for bucket, cogs, missing in cost_rows}

    tender_rows = await session.execute(
        select(sale_bucket, func.sum(Payment.amount))
        .select_from(Payment)
        .join(Sale, Sale.id == Payment.sale_id)
        .where(
            Payment.business_id == business_id,
            Payment.status == PaymentStatus.CONFIRMED,
            Payment.method != PaymentMethod.CREDIT,
            *_completed_sales_in(business_id, period),
        )
        .group_by(sale_bucket)
    )
    cash = {bucket: _money(total) for bucket, total in tender_rows}
    repayment_bucket = _bucket_expr(
        CreditTransaction.occurred_at, granularity, period.timezone
    ).label("bucket")
    repayment_rows = await session.execute(
        select(repayment_bucket, func.sum(-CreditTransaction.amount))
        .where(
            CreditTransaction.business_id == business_id,
            CreditTransaction.entry_type == CreditEntryType.REPAYMENT,
            CreditTransaction.occurred_at >= period.start,
            CreditTransaction.occurred_at < period.end,
        )
        .group_by(repayment_bucket)
    )
    for bucket, total in repayment_rows:
        cash[bucket] = cash.get(bucket, ZERO) + _money(total)

    expense_bucket = _bucket_expr(Expense.incurred_at, granularity, period.timezone).label("bucket")
    expense_rows = await session.execute(
        select(expense_bucket, func.sum(Expense.amount))
        .where(
            Expense.business_id == business_id,
            Expense.deleted_at.is_(None),
            Expense.incurred_at >= period.start,
            Expense.incurred_at < period.end,
        )
        .group_by(expense_bucket)
    )
    expenses = {bucket: _money(total) for bucket, total in expense_rows}

    result: list[Bucket] = []
    for bucket in sorted(set(buckets) | set(cash) | set(expenses)):
        count, revenue, discounts = buckets.get(bucket, (0, ZERO, ZERO))
        cogs, missing = costs.get(bucket, (ZERO, 0))
        gross_profit = revenue - cogs
        spent = expenses.get(bucket, ZERO)
        result.append(
            Bucket(
                bucket_start=bucket,
                sales_count=count,
                revenue=revenue,
                discounts=discounts,
                cogs=cogs,
                lines_missing_cost=missing,
                gross_profit=gross_profit,
                cash_collected=cash.get(bucket, ZERO),
                expenses=spent,
                net_profit=gross_profit - spent,
            )
        )
    return result


# --- products ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProductPerformance:
    product_id: uuid.UUID
    name: str
    is_active: bool
    category_id: uuid.UUID | None
    quantity: Decimal
    revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    sales_count: int
    lines_missing_cost: int


async def product_performance(
    session: AsyncSession, business_id: uuid.UUID, period: Period, *, sort: ProductSort, limit: int
) -> list[ProductPerformance]:
    revenue = func.sum(_LINE_REVENUE).label("revenue")
    cogs = func.coalesce(func.sum(_COGS_LINE), 0).label("cogs")
    quantity = func.sum(SaleItem.quantity).label("quantity")
    profit = (func.sum(_LINE_REVENUE) - func.coalesce(func.sum(_COGS_LINE), 0)).label("profit")
    stmt = (
        select(
            Product.id,
            Product.name,
            Product.is_active,
            Product.category_id,
            quantity,
            revenue,
            cogs,
            profit,
            func.count(func.distinct(SaleItem.sale_id)),
            func.count(case((SaleItem.unit_cost.is_(None), 1))),
        )
        .select_from(SaleItem)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .where(SaleItem.business_id == business_id, *_completed_sales_in(business_id, period))
        .group_by(Product.id)
    )
    order = {"quantity": quantity, "revenue": revenue, "profit": profit}[sort]
    stmt = stmt.order_by(order.desc(), func.lower(Product.name), Product.id).limit(
        min(limit, MAX_ROWS)
    )
    rows = await session.execute(stmt)
    return [
        ProductPerformance(
            product_id=pid,
            name=name,
            is_active=active,
            category_id=category_id,
            quantity=_quantity(qty),
            revenue=_money(rev),
            cogs=_money(cost),
            gross_profit=_money(rev) - _money(cost),
            sales_count=int(sales),
            lines_missing_cost=int(missing),
        )
        for pid, name, active, category_id, qty, rev, cost, _profit, sales, missing in rows
    ]


@dataclass(frozen=True, slots=True)
class SlowProduct:
    product_id: uuid.UUID
    name: str
    stock_quantity: Decimal
    last_sold_at: datetime | None


async def slow_products(
    session: AsyncSession, business_id: uuid.UUID, *, since: datetime, limit: int
) -> list[SlowProduct]:
    """FR-I3: active, tracked products with stock on hand and no COMPLETED sale since `since`.

    The last sale date is computed once per product in a derived table (one pass over the
    tenant's sale lines) and outer-joined; a correlated subquery here was evaluated three
    times per product, each a full scan of `sales`, and took seconds on a 40k-sale tenant.
    """
    last_sales = (
        select(SaleItem.product_id.label("product_id"), func.max(Sale.sold_at).label("last"))
        .select_from(SaleItem)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(SaleItem.business_id == business_id, Sale.status == SaleStatus.COMPLETED)
        .group_by(SaleItem.product_id)
        .subquery("last_sales")
    )
    last_sold = last_sales.c.last
    stmt = (
        select(Product.id, Product.name, Product.stock_quantity, last_sold.label("last_sold_at"))
        .select_from(Product)
        .outerjoin(last_sales, last_sales.c.product_id == Product.id)
        .where(
            Product.business_id == business_id,
            Product.is_active.is_(True),
            Product.track_inventory.is_(True),
            Product.stock_quantity > 0,
        )
        .where((last_sold.is_(None)) | (last_sold < since))
        .order_by(
            text("last_sold_at ASC NULLS FIRST"),
            Product.stock_quantity.desc(),
            func.lower(Product.name),
            Product.id,
        )
        .limit(min(limit, MAX_ROWS))
    )
    rows = await session.execute(stmt)
    return [
        SlowProduct(product_id=pid, name=name, stock_quantity=_quantity(stock), last_sold_at=last)
        for pid, name, stock, last in rows
    ]


# --- categories ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CategoryPerformance:
    category_id: uuid.UUID | None  # None = uncategorised products
    name: str | None
    quantity: Decimal
    revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    lines_missing_cost: int


async def category_performance(
    session: AsyncSession, business_id: uuid.UUID, period: Period
) -> list[CategoryPerformance]:
    revenue = func.sum(_LINE_REVENUE).label("revenue")
    stmt = (
        select(
            Product.category_id,
            func.max(Category.name),
            func.sum(SaleItem.quantity),
            revenue,
            func.coalesce(func.sum(_COGS_LINE), 0),
            func.count(case((SaleItem.unit_cost.is_(None), 1))),
        )
        .select_from(SaleItem)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .outerjoin(
            Category, (Category.id == Product.category_id) & (Category.business_id == business_id)
        )
        .where(SaleItem.business_id == business_id, *_completed_sales_in(business_id, period))
        .group_by(Product.category_id)
        .order_by(revenue.desc(), func.max(Category.name).asc().nulls_last(), Product.category_id)
    )
    rows = await session.execute(stmt)
    return [
        CategoryPerformance(
            category_id=cid,
            name=name,
            quantity=_quantity(qty),
            revenue=_money(rev),
            cogs=_money(cost),
            gross_profit=_money(rev) - _money(cost),
            lines_missing_cost=int(missing),
        )
        for cid, name, qty, rev, cost, missing in rows
    ]


# --- expenses (FR-I6) -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExpenseGroup:
    key: str  # category name or payment method
    total: Decimal
    count: int


@dataclass(frozen=True, slots=True)
class ExpenseBreakdown:
    total: Decimal
    count: int
    by_category: list[ExpenseGroup]
    by_method: dict[str, Decimal]


async def expense_breakdown(
    session: AsyncSession, business_id: uuid.UUID, period: Period
) -> ExpenseBreakdown:
    """Non-deleted expenses with `incurred_at` in the period, by category and by method."""
    by_category = [
        ExpenseGroup(key=category, total=_money(total), count=count)
        for category, total, count in await expense_repo.totals_by_category(
            session, business_id, incurred_from=period.start, incurred_until=period.end
        )
    ]
    by_method = {method.value: ZERO for method in MoneyReceivedMethod}
    for method, total, _count in await expense_repo.totals_by_method(
        session, business_id, incurred_from=period.start, incurred_until=period.end
    ):
        by_method[method.value] = _money(total)
    return ExpenseBreakdown(
        total=sum((g.total for g in by_category), ZERO),
        count=sum(g.count for g in by_category),
        by_category=by_category,
        by_method=by_method,
    )


__all__ = [
    "Bucket",
    "CategoryPerformance",
    "ExpenseBreakdown",
    "ExpenseGroup",
    "ProductPerformance",
    "SlowProduct",
    "Summary",
    "category_performance",
    "expense_breakdown",
    "product_performance",
    "slow_products",
    "summary",
    "timeseries",
]
