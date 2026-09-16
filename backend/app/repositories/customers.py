"""customers (docs/DATA_MAPPING.md §3.8). Every query is scoped by `business_id`.

Search (PRD FR-G / §20 `search_customers`) is what a shopkeeper needs mid-sale:
a case-insensitive *substring* of the name ("njeri" finds "Mama Njeri") or a
prefix of the phone number, both parameterised, LIKE wildcards escaped.
"""

import re
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.models import Customer

MAX_LIST_LIMIT = 500
_PHONE_CHARS = re.compile(r"^[+\d][\d\s\-().]*$")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _phone_pattern(query: str) -> str | None:
    """LIKE pattern for a partly typed phone number, or None when `query` is not one.

    Mirrors `schemas.identifiers.normalize_phone` for incomplete input: `07…` / `01…`
    → `+254…`, `00…` / `254…` → `+…`, `+…` as typed — all matched as prefixes of the
    stored E.164 value. Bare digits without a country or trunk prefix (`712345678`,
    `345678`) match anywhere in the number.
    """
    if not _PHONE_CHARS.fullmatch(query):
        return None
    digits = re.sub(r"[\s\-().]", "", query)
    if len(digits) < 2:
        return None
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    elif digits.startswith("0"):
        digits = "+254" + digits[1:]
    elif digits.startswith("254"):
        digits = "+" + digits
    elif not digits.startswith("+"):
        return "%" + _escape_like(digits) + "%"
    return _escape_like(digits) + "%"


def _search_clause(query: str) -> ColumnElement[bool]:
    needle = _escape_like(query.lower())
    clauses = [func.lower(Customer.name).like(f"%{needle}%", escape="\\")]
    pattern = _phone_pattern(query)
    if pattern is not None:
        clauses.append(Customer.phone.like(pattern, escape="\\"))
    return or_(*clauses)


async def list_customers(
    session: AsyncSession,
    business_id: uuid.UUID,
    *,
    query: str | None = None,
    include_archived: bool = False,
    limit: int = MAX_LIST_LIMIT,
) -> list[Customer]:
    stmt = select(Customer).where(Customer.business_id == business_id)
    if not include_archived:
        stmt = stmt.where(Customer.is_active.is_(True))
    if query:
        stmt = stmt.where(_search_clause(query))
    stmt = stmt.order_by(func.lower(Customer.name), Customer.id).limit(min(limit, MAX_LIST_LIMIT))
    return list(await session.scalars(stmt))


async def get_customer(
    session: AsyncSession, *, business_id: uuid.UUID, customer_id: uuid.UUID
) -> Customer | None:
    result = await session.scalars(
        select(Customer).where(Customer.business_id == business_id, Customer.id == customer_id)
    )
    return result.one_or_none()
