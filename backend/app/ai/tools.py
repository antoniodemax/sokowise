"""The allowlisted, read-only tools the model can call (PRD AI-2, AI-3; ARCHITECTURE §6.2).

Every tool takes the authenticated `BusinessContext` from the request — no tool has
a `business_id` argument, so the model cannot name a business. Inputs are strict
Pydantic models (unknown fields rejected); outputs are compact JSON-safe dicts with
bounded row counts. Tools read through `analytics` and named repository functions
only; they never import `services`.
"""

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.periods import AIPeriod, PeriodError, local_today, resolve_ai_period
from app.analytics import queries
from app.analytics.periods import Period
from app.core.context import BusinessContext
from app.repositories.credit import list_debtors as repo_list_debtors
from app.repositories.customers import list_customers as repo_list_customers
from app.repositories.inventory import list_low_stock as repo_list_low_stock
from app.schemas.business import BusinessSettings

MAX_ROWS = 50
MAX_TOOL_OUTPUT_CHARS = 12_000
CURRENCY = "KES"


class ToolInputError(ValueError):
    """Bad arguments; the message goes back to the model as an error tool result."""


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _qty(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.001')).normalize():f}"


def _period_out(period: Period) -> dict[str, str]:
    return {
        "date_from": period.date_from.isoformat(),
        "date_to": period.date_to.isoformat(),
        "timezone": period.timezone,
    }


class PeriodInput(BaseModel):
    """`period` names a range relative to today in the business timezone; `custom` needs both dates."""

    model_config = ConfigDict(extra="forbid")

    period: AIPeriod = Field(
        description="today, yesterday, this_week, last_week, this_month, last_month or custom"
    )
    date_from: date | None = Field(
        default=None, description="First day (YYYY-MM-DD), only for custom"
    )
    date_to: date | None = Field(default=None, description="Last day (YYYY-MM-DD), only for custom")

    def resolve(self, ctx: BusinessContext, now: datetime | None) -> Period:
        try:
            return resolve_ai_period(
                ctx.timezone, self.period, self.date_from, self.date_to, now=now
            )
        except PeriodError as exc:
            raise ToolInputError(str(exc)) from None


# --- tools ---------------------------------------------------------------------------------


def _summary_out(summary: queries.Summary, period: Period) -> dict[str, Any]:
    return {
        "currency": CURRENCY,
        "period": _period_out(period),
        "sales_count": summary.sales_count,
        "revenue": _money(summary.revenue),
        "discounts": _money(summary.discounts),
        "cash_collected_total": _money(summary.cash_collected_total),
        "cash_collected_by_method": {k: _money(v) for k, v in summary.cash_collected.items()},
        "sold_by_tender": {k: _money(v) for k, v in summary.tender_split.items()},
        "receivables_outstanding_now": _money(summary.receivables_outstanding),
        "cogs": _money(summary.cogs),
        "gross_profit": _money(summary.gross_profit),
        "expenses": _money(summary.expenses),
        "net_profit": _money(summary.net_profit),
        "lines_missing_cost": summary.lines_missing_cost,
        "products_missing_cost": summary.products_missing_cost,
        "notes": [
            "revenue counts completed sales including credit sales",
            "cash_collected_total = CASH + MPESA payments on sales + customer repayments in the period; CREDIT is never cash",
            "sold_by_tender.CREDIT is the amount sold on credit (a receivable)",
            "gross_profit = revenue - cogs; net_profit = gross_profit - expenses",
        ]
        + (
            [
                f"{summary.lines_missing_cost} sale line(s) from {summary.products_missing_cost} product(s) have no cost price, so cogs is incomplete and gross/net profit are understated"
            ]
            if summary.lines_missing_cost
            else []
        ),
    }


async def get_business_summary(
    session: AsyncSession, ctx: BusinessContext, args: PeriodInput, now: datetime | None
) -> dict[str, Any]:
    period = args.resolve(ctx, now)
    summary = await queries.summary(session, ctx.business_id, period)
    return _summary_out(summary, period)


class SalesSummaryInput(PeriodInput):
    top_products_limit: int = Field(
        default=5, ge=0, le=10, description="How many best-selling products to include"
    )


async def get_sales_summary(
    session: AsyncSession, ctx: BusinessContext, args: SalesSummaryInput, now: datetime | None
) -> dict[str, Any]:
    period = args.resolve(ctx, now)
    summary = await queries.summary(session, ctx.business_id, period)
    out = {
        "currency": CURRENCY,
        "period": _period_out(period),
        "sales_count": summary.sales_count,
        "revenue": _money(summary.revenue),
        "discounts": _money(summary.discounts),
        "sold_by_tender": {k: _money(v) for k, v in summary.tender_split.items()},
        "cash_collected_total": _money(summary.cash_collected_total),
        "cash_collected_by_method": {k: _money(v) for k, v in summary.cash_collected.items()},
        "receivables_outstanding_now": _money(summary.receivables_outstanding),
        "notes": [
            "revenue = completed sales in the period including credit sales",
            "cash_collected_total includes customer repayments received in the period and excludes CREDIT",
        ],
    }
    if args.top_products_limit:
        rows = await queries.product_performance(
            session, ctx.business_id, period, sort="revenue", limit=args.top_products_limit
        )
        out["top_products_by_revenue"] = [
            {"name": r.name, "quantity": _qty(r.quantity), "revenue": _money(r.revenue)}
            for r in rows
        ]
    return out


class ProductPerformanceInput(PeriodInput):
    sort: Literal["quantity", "revenue", "profit"] = Field(
        default="revenue", description="Order: most sold, most revenue or most gross profit first"
    )
    limit: int = Field(default=10, ge=1, le=20)


async def get_product_performance(
    session: AsyncSession, ctx: BusinessContext, args: ProductPerformanceInput, now: datetime | None
) -> dict[str, Any]:
    period = args.resolve(ctx, now)
    rows = await queries.product_performance(
        session, ctx.business_id, period, sort=args.sort, limit=args.limit
    )
    return {
        "currency": CURRENCY,
        "period": _period_out(period),
        "sorted_by": args.sort,
        "products": [
            {
                "name": r.name,
                "quantity": _qty(r.quantity),
                "sales_count": r.sales_count,
                "revenue": _money(r.revenue),
                "cogs": _money(r.cogs),
                "gross_profit": _money(r.gross_profit),
                "lines_missing_cost": r.lines_missing_cost,
                "archived": not r.is_active,
            }
            for r in rows
        ],
        "notes": [
            "a product with lines_missing_cost > 0 has an understated cogs and overstated gross_profit"
        ],
    }


class SlowProductsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(
        default=30, ge=1, le=90, description="Products with stock but no sale in this many days"
    )
    limit: int = Field(default=10, ge=1, le=20)


async def get_slow_products(
    session: AsyncSession, ctx: BusinessContext, args: SlowProductsInput, now: datetime | None
) -> dict[str, Any]:
    since = (now or datetime.now(UTC)) - timedelta(days=args.days)
    rows = await queries.slow_products(session, ctx.business_id, since=since, limit=args.limit)
    return {
        "days_without_sale": args.days,
        "products": [
            {
                "name": r.name,
                "stock_quantity": _qty(r.stock_quantity),
                "last_sold_at": r.last_sold_at.isoformat() if r.last_sold_at else None,
            }
            for r in rows
        ],
    }


class InventoryStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(
        default=20, ge=1, le=MAX_ROWS, description="Maximum low-stock products to return"
    )


async def get_inventory_status(
    session: AsyncSession, ctx: BusinessContext, args: InventoryStatusInput, now: datetime | None
) -> dict[str, Any]:
    settings = BusinessSettings.model_validate(ctx.settings)
    default_threshold = Decimal(settings.low_stock_default_threshold).quantize(Decimal("0.001"))
    rows = await repo_list_low_stock(
        session, ctx.business_id, default_threshold=default_threshold, limit=args.limit
    )
    return {
        "default_low_stock_threshold": _qty(default_threshold),
        "low_stock_products": [
            {
                "name": product.name,
                "stock_quantity": _qty(product.stock_quantity),
                "unit": product.unit,
                "threshold": _qty(threshold),
                "out_of_stock": product.stock_quantity <= 0,
            }
            for product, threshold in rows
        ],
        "notes": [
            "only active products that track stock are listed; a product at or below its threshold needs restocking"
        ],
    }


class DebtorsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sort: Literal["balance", "age"] = Field(
        default="balance", description="Largest debt first, or oldest unpaid debt first"
    )
    limit: int = Field(default=10, ge=1, le=MAX_ROWS)


async def get_debtors(
    session: AsyncSession, ctx: BusinessContext, args: DebtorsInput, now: datetime | None
) -> dict[str, Any]:
    rows = await repo_list_debtors(session, ctx.business_id, sort=args.sort, limit=args.limit)
    total = sum((row.customer.balance for row in rows), Decimal(0))
    return {
        "currency": CURRENCY,
        "sorted_by": args.sort,
        "debtors": [
            {
                "customer_id": str(row.customer.id),
                "name": row.customer.name,
                "balance": _money(row.customer.balance),
                "credit_limit": _money(row.customer.credit_limit)
                if row.customer.credit_limit is not None
                else None,
                "oldest_unpaid_charge_at": row.oldest_unpaid_charge_at.isoformat()
                if row.oldest_unpaid_charge_at
                else None,
            }
            for row in rows
        ],
        "listed_total": _money(total),
        "notes": [
            "listed_total sums only the debtors listed here; the full receivables figure is in get_business_summary"
        ],
    }


class ExpenseSummaryInput(PeriodInput):
    pass


async def get_expense_summary(
    session: AsyncSession, ctx: BusinessContext, args: ExpenseSummaryInput, now: datetime | None
) -> dict[str, Any]:
    period = args.resolve(ctx, now)
    breakdown = await queries.expense_breakdown(session, ctx.business_id, period)
    return {
        "currency": CURRENCY,
        "period": _period_out(period),
        "total": _money(breakdown.total),
        "count": breakdown.count,
        "by_category": [
            {"category": g.key, "total": _money(g.total), "count": g.count}
            for g in breakdown.by_category[:MAX_ROWS]
        ],
        "by_payment_method": {k: _money(v) for k, v in breakdown.by_method.items()},
        "notes": ["operating expenses only; buying stock (restocks) is not an expense"],
    }


class SearchCustomersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(
        min_length=1, max_length=80, description="Part of a customer's name, or a phone number"
    )
    limit: int = Field(default=5, ge=1, le=10)


async def search_customers(
    session: AsyncSession, ctx: BusinessContext, args: SearchCustomersInput, now: datetime | None
) -> dict[str, Any]:
    rows = await repo_list_customers(
        session, ctx.business_id, query=args.query.strip(), include_archived=False, limit=args.limit
    )
    return {
        "currency": CURRENCY,
        "customers": [
            {
                "customer_id": str(c.id),
                "name": c.name,
                "balance_owed": _money(c.balance),
                "credit_limit": _money(c.credit_limit) if c.credit_limit is not None else None,
            }
            for c in rows
        ],
        "notes": [
            "balance_owed > 0 means the customer owes the business; phone numbers are not included"
        ],
    }


# --- registry ------------------------------------------------------------------------------

ToolFn = Callable[[AsyncSession, BusinessContext, Any, datetime | None], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    run: ToolFn

    def input_schema(self) -> dict[str, Any]:
        """Strict JSON schema: every property listed as required, no extras (PRD AI-2)."""
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        schema.pop("description", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        for definition in schema.get("$defs", {}).values():
            definition.pop("title", None)
        schema["required"] = sorted(schema.get("properties", {}).keys())
        schema["additionalProperties"] = False
        return schema

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema(),
            "strict": True,
        }


_PERIOD_HELP = " Ask for a period: today, yesterday, this_week, last_week, this_month, last_month, or custom with date_from and date_to (pass null for the dates otherwise)."

TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool(
            "get_business_summary",
            "The business's figures for a period: sales count, revenue, cash collected (by method), what was sold on credit, receivables now, cost of goods, gross profit, expenses, net profit and any missing-cost warning. Use for 'how much did I make', profit, cash and overview questions."
            + _PERIOD_HELP,
            PeriodInput,
            get_business_summary,
        ),
        Tool(
            "get_sales_summary",
            "Sales for a period: count, revenue, split by tender (cash, M-Pesa, credit), cash collected, and optionally the best-selling products by revenue. Use for questions about sales, takings or how sales were paid."
            + _PERIOD_HELP,
            SalesSummaryInput,
            get_sales_summary,
        ),
        Tool(
            "get_product_performance",
            "Products ranked for a period by quantity sold, revenue or gross profit, with cost of goods and missing-cost flags. Use for 'what sold most', 'most profitable products' and product comparisons."
            + _PERIOD_HELP,
            ProductPerformanceInput,
            get_product_performance,
        ),
        Tool(
            "get_slow_products",
            "Products that have stock on hand but no sale in the last N days (default 30). Use for 'what is not selling'.",
            SlowProductsInput,
            get_slow_products,
        ),
        Tool(
            "get_inventory_status",
            "Products at or below their low-stock threshold, with current stock, unit and threshold. Use for 'what should I restock' and stock questions.",
            InventoryStatusInput,
            get_inventory_status,
        ),
        Tool(
            "get_debtors",
            "Customers who currently owe the business money, with balances, credit limits and how long the oldest unpaid debt has been open. Use for 'who owes me money'.",
            DebtorsInput,
            get_debtors,
        ),
        Tool(
            "get_expense_summary",
            "Operating expenses for a period: total, count, by category and by payment method. Use for 'how much did I spend' and 'biggest expenses'."
            + _PERIOD_HELP,
            ExpenseSummaryInput,
            get_expense_summary,
        ),
        Tool(
            "search_customers",
            "Find customers by part of their name or by phone number; returns each one's balance owed. Use when the user names a customer.",
            SearchCustomersInput,
            search_customers,
        ),
    )
}


def tool_definitions() -> list[dict[str, Any]]:
    return [tool.definition() for tool in TOOLS.values()]


def serialise_result(result: dict[str, Any]) -> str:
    """Compact JSON for the tool_result block; oversized outputs are refused, never cut mid-value."""
    text = json.dumps(result, separators=(",", ":"), default=str)
    if len(text) > MAX_TOOL_OUTPUT_CHARS:
        return json.dumps(
            {"error": "The result is too large; ask for fewer rows or a shorter period"}
        )
    return text


def parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ToolInputError("Not a valid id") from None


__all__ = [
    "MAX_ROWS",
    "TOOLS",
    "Tool",
    "ToolInputError",
    "local_today",
    "serialise_result",
    "tool_definitions",
]
