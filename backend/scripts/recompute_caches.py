"""Compare (and optionally repair) `products.stock_quantity` against the movement ledger.

    uv run --env-file ../.env python scripts/recompute_caches.py            # report only
    uv run --env-file ../.env python scripts/recompute_caches.py --apply    # repair

Runs the same `services.inventory.recompute_stock` the OWNER endpoint uses, for every
business, under a system context (audit rows carry the business's oldest active owner
as actor so they stay attributable). Customer balances are not covered here.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.context import BusinessContext
from app.db.session import create_engine, create_session_factory
from app.models import Business, BusinessMembership
from app.models.enums import MembershipRole
from app.services.inventory import recompute_stock
from sqlalchemy import select


async def main(apply: bool) -> int:
    engine = create_engine(get_settings())
    factory = create_session_factory(engine)
    drift = 0
    try:
        async with factory() as session:
            businesses = list(await session.scalars(select(Business).order_by(Business.id)))
            for business in businesses:
                owner = await session.scalar(
                    select(BusinessMembership)
                    .where(
                        BusinessMembership.business_id == business.id,
                        BusinessMembership.role == MembershipRole.OWNER,
                        BusinessMembership.is_active.is_(True),
                    )
                    .order_by(BusinessMembership.created_at, BusinessMembership.id)
                )
                if owner is None:
                    print(f"{business.id}: no active owner, skipped")
                    continue
                ctx = BusinessContext(
                    user_id=owner.user_id,
                    business_id=business.id,
                    membership_id=owner.id,
                    role=MembershipRole.OWNER,
                    timezone=business.timezone,
                    settings=dict(business.settings),
                )
                result = await recompute_stock(session, ctx, apply=apply)
                for d in result.discrepancies:
                    drift += 1
                    verb = "repaired" if d.repaired else "drift"
                    print(
                        f"{business.id} product {d.product_id}: "
                        f"cache {d.cached_stock} ledger {d.ledger_stock} ({verb})"
                    )
                print(
                    f"{business.id}: {result.products_checked} tracked products checked, "
                    f"{len(result.discrepancies)} discrepancies"
                )
    finally:
        await engine.dispose()
    return 1 if drift and not apply else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="rewrite caches that disagree with the ledger"
    )
    raise SystemExit(asyncio.run(main(parser.parse_args().apply)))
