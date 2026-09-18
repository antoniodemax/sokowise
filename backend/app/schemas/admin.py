"""Operator dashboard responses (docs/ARCHITECTURE.md §5.4). Counts and totals only."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class TotalsOut(BaseModel):
    businesses: int
    businesses_active: int
    users: int
    owners: int
    staff: int
    products: int
    customers: int
    sales: int
    revenue: Decimal
    expenses: int
    credit_outstanding: Decimal
    mpesa_messages: int
    receipts: int
    copilot_messages: int
    proposals_applied: int


class RecentOut(BaseModel):
    days: int
    new_businesses: int
    sales: int
    revenue: Decimal
    businesses_with_sales: int
    users_signed_in: int


class SignupBucketOut(BaseModel):
    day: date
    businesses: int


class BusinessRowOut(BaseModel):
    """One tenant as the operator sees it: name and counts, never phones or money."""

    id: uuid.UUID
    name: str
    business_type: str
    is_active: bool
    created_at: datetime
    products: int
    sales: int
    last_sale_at: datetime | None
    last_login_at: datetime | None


class PlatformOverviewOut(BaseModel):
    generated_at: datetime
    timezone: str
    totals: TotalsOut
    last_7_days: RecentOut
    last_30_days: RecentOut
    signups_by_day: list[SignupBucketOut]
    businesses: list[BusinessRowOut]


class BusinessDeletedOut(BaseModel):
    business_id: uuid.UUID
    name: str
    users_deleted: int
    receipt_images_deleted: int
