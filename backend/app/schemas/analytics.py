"""Analytics responses (PRD FR-I). Money as Decimal strings; dates are business-local."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class PeriodOut(BaseModel):
    timezone: str
    date_from: date  # inclusive, local calendar day
    date_to: date  # inclusive, local calendar day


class SummaryOut(BaseModel):
    period: PeriodOut
    sales_count: int
    revenue: Decimal  # accrual: COMPLETED sales, credit included
    discounts: Decimal
    cogs: Decimal  # from sale-time unit_cost snapshots; unknown costs contribute 0
    lines_missing_cost: int
    products_missing_cost: int
    gross_profit: Decimal  # revenue - cogs (understated by the missing-cost lines)
    expenses: Decimal
    net_profit: Decimal
    tender_split: dict[str, Decimal]  # CASH / MPESA / CREDIT tenders on period sales
    cash_collected: dict[str, Decimal]  # CASH / MPESA tenders + credit repayments, by method
    cash_collected_total: Decimal
    receivables_outstanding: Decimal  # Σ positive customer balances, right now


class BucketOut(BaseModel):
    bucket_start: date
    sales_count: int
    revenue: Decimal
    discounts: Decimal
    cogs: Decimal
    lines_missing_cost: int
    gross_profit: Decimal
    cash_collected: Decimal
    expenses: Decimal
    net_profit: Decimal


class TimeseriesOut(BaseModel):
    period: PeriodOut
    granularity: str
    buckets: list[BucketOut]


class ProductPerformanceOut(BaseModel):
    product_id: uuid.UUID
    name: str
    is_active: bool  # archived products keep their history
    category_id: uuid.UUID | None
    quantity: Decimal
    revenue: Decimal  # Σ line_total - discount_allocated
    cogs: Decimal
    gross_profit: Decimal
    sales_count: int
    lines_missing_cost: int


class SlowProductOut(BaseModel):
    product_id: uuid.UUID
    name: str
    stock_quantity: Decimal
    last_sold_at: datetime | None


class CategoryPerformanceOut(BaseModel):
    category_id: uuid.UUID | None  # null = products without a category
    name: str | None
    quantity: Decimal
    revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    lines_missing_cost: int


class ExpenseGroupOut(BaseModel):
    key: str  # category name (free text, upper-cased) or payment method
    total: Decimal
    count: int


class ExpenseBreakdownOut(BaseModel):
    period: PeriodOut
    total: Decimal
    count: int
    by_category: list[ExpenseGroupOut]  # largest first, then name
    by_method: dict[str, Decimal]  # CASH / MPESA
