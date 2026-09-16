"""The database rejects rows that break the documented invariants, using real INSERTs."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.models import (
    AIConversation,
    Business,
    BusinessMembership,
    Category,
    Product,
    Sale,
    User,
)
from app.models.enums import BusinessType, MembershipRole, SaleStatus
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def _business(session: AsyncSession, name: str = "Amina Duka") -> Business:
    business = Business(name=name, business_type=BusinessType.GENERAL_SHOP)
    session.add(business)
    await session.flush()
    return business


async def _user(session: AsyncSession, phone: str = "+254700000001") -> User:
    user = User(phone=phone, full_name="Test User", password_hash="not-a-real-hash")  # noqa: S106
    session.add(user)
    await session.flush()
    return user


async def _expect_violation(
    session: AsyncSession, constraint: str, action: Callable[[], Awaitable[object]]
) -> None:
    with pytest.raises(IntegrityError) as exc_info:
        async with session.begin_nested():
            await action()
            await session.flush()
    assert constraint in str(exc_info.value)


async def test_business_and_owner_membership_round_trip(db_session: AsyncSession) -> None:
    business = await _business(db_session)
    user = await _user(db_session)
    db_session.add(
        BusinessMembership(business_id=business.id, user_id=user.id, role=MembershipRole.OWNER)
    )
    await db_session.flush()
    row = (
        await db_session.execute(
            text("SELECT role, is_active FROM business_memberships WHERE user_id = :uid"),
            {"uid": user.id},
        )
    ).one()
    assert row == ("OWNER", True)
    assert business.currency == "KES" or business.currency is None  # server default until refresh
    await db_session.refresh(business)
    assert (business.currency, business.timezone, business.settings) == (
        "KES",
        "Africa/Nairobi",
        {},
    )


async def test_membership_is_unique_per_user_and_business(db_session: AsyncSession) -> None:
    business = await _business(db_session)
    user = await _user(db_session)
    db_session.add(
        BusinessMembership(business_id=business.id, user_id=user.id, role=MembershipRole.OWNER)
    )
    await db_session.flush()

    async def duplicate() -> None:
        db_session.add(
            BusinessMembership(business_id=business.id, user_id=user.id, role=MembershipRole.STAFF)
        )

    await _expect_violation(db_session, "uq_business_memberships_business_id_user_id", duplicate)


async def test_role_check_rejects_unknown_role(db_session: AsyncSession) -> None:
    business = await _business(db_session)
    user = await _user(db_session)

    async def bad_role() -> None:
        await db_session.execute(
            text(
                "INSERT INTO business_memberships (id, business_id, user_id, role, updated_at) "
                "VALUES (:id, :bid, :uid, 'MANAGER', now())"
            ),
            {"id": uuid.uuid4(), "bid": business.id, "uid": user.id},
        )

    await _expect_violation(db_session, "ck_business_memberships_role", bad_role)


async def test_product_cannot_reference_another_businesss_category(
    db_session: AsyncSession,
) -> None:
    """The composite FK is the database backstop for tenant isolation."""
    business_a = await _business(db_session, "A")
    business_b = await _business(db_session, "B")
    category_a = Category(business_id=business_a.id, name="Drinks")
    db_session.add(category_a)
    await db_session.flush()

    async def cross_tenant() -> None:
        db_session.add(
            Product(
                business_id=business_b.id,
                category_id=category_a.id,
                name="Soda",
                selling_price=Decimal("50.00"),
            )
        )

    await _expect_violation(
        db_session, "fk_products_category_id_business_id_categories", cross_tenant
    )


async def test_active_product_names_are_unique_per_business_case_insensitively(
    db_session: AsyncSession,
) -> None:
    business = await _business(db_session)
    db_session.add(Product(business_id=business.id, name="Sugar 1kg", selling_price=Decimal("180")))
    await db_session.flush()

    async def duplicate_name() -> None:
        db_session.add(
            Product(business_id=business.id, name="SUGAR 1KG", selling_price=Decimal("185"))
        )

    await _expect_violation(db_session, "uq_products_business_id_lower_name_active", duplicate_name)

    # An archived product may share the name (partial index).
    db_session.add(
        Product(
            business_id=business.id,
            name="sugar 1kg",
            selling_price=Decimal("185"),
            is_active=False,
        )
    )
    await db_session.flush()


async def test_sale_total_must_equal_subtotal_minus_discount(db_session: AsyncSession) -> None:
    business = await _business(db_session)
    user = await _user(db_session)

    def sale(total: str) -> Sale:
        return Sale(
            business_id=business.id,
            idempotency_key=uuid.uuid4(),
            idempotency_hash="a" * 64,
            status=SaleStatus.COMPLETED,
            subtotal=Decimal("100.00"),
            discount_amount=Decimal("10.00"),
            total_amount=Decimal(total),
            sold_at=datetime.now(tz=UTC),
            created_by=user.id,
        )

    async def wrong_total() -> None:
        db_session.add(sale("100.00"))

    await _expect_violation(db_session, "ck_sales_total_amount", wrong_total)
    db_session.add(sale("90.00"))
    await db_session.flush()


async def test_sale_idempotency_key_is_unique_per_business(db_session: AsyncSession) -> None:
    business = await _business(db_session)
    user = await _user(db_session)
    key = uuid.uuid4()

    def sale(hash_char: str) -> Sale:
        return Sale(
            business_id=business.id,
            idempotency_key=key,
            idempotency_hash=hash_char * 64,
            status=SaleStatus.COMPLETED,
            subtotal=Decimal("10"),
            total_amount=Decimal("10"),
            sold_at=datetime.now(tz=UTC),
            created_by=user.id,
        )

    db_session.add(sale("a"))
    await db_session.flush()

    async def replay_with_different_payload() -> None:
        db_session.add(sale("b"))  # same key, different hash: the service will answer 409

    await _expect_violation(
        db_session, "uq_sales_business_id_idempotency_key", replay_with_different_payload
    )


async def test_ai_messages_reject_system_role(db_session: AsyncSession) -> None:
    business = await _business(db_session)
    user = await _user(db_session)
    conversation = AIConversation(business_id=business.id, user_id=user.id)
    db_session.add(conversation)
    await db_session.flush()

    async def system_message() -> None:
        await db_session.execute(
            text(
                "INSERT INTO ai_messages (id, business_id, conversation_id, role, content) "
                "VALUES (:id, :bid, :cid, 'system', 'nope')"
            ),
            {"id": uuid.uuid4(), "bid": business.id, "cid": conversation.id},
        )

    await _expect_violation(db_session, "ck_ai_messages_role", system_message)


async def test_payment_credit_is_a_distinct_tender_and_amount_must_be_positive(
    db_session: AsyncSession,
) -> None:
    business = await _business(db_session)
    user = await _user(db_session)
    sale = Sale(
        business_id=business.id,
        idempotency_key=uuid.uuid4(),
        idempotency_hash="c" * 64,
        status=SaleStatus.COMPLETED,
        subtotal=Decimal("500"),
        total_amount=Decimal("500"),
        sold_at=datetime.now(tz=UTC),
        created_by=user.id,
    )
    db_session.add(sale)
    await db_session.flush()

    async def zero_amount() -> None:
        await db_session.execute(
            text(
                "INSERT INTO payments (id, business_id, sale_id, method, amount) "
                "VALUES (:id, :bid, :sid, 'CREDIT', 0)"
            ),
            {"id": uuid.uuid4(), "bid": business.id, "sid": sale.id},
        )

    await _expect_violation(db_session, "ck_payments_amount_positive", zero_amount)

    async def unknown_method() -> None:
        await db_session.execute(
            text(
                "INSERT INTO payments (id, business_id, sale_id, method, amount) "
                "VALUES (:id, :bid, :sid, 'CARD', 10)"
            ),
            {"id": uuid.uuid4(), "bid": business.id, "sid": sale.id},
        )

    await _expect_violation(db_session, "ck_payments_method", unknown_method)

    await db_session.execute(
        text(
            "INSERT INTO payments (id, business_id, sale_id, method, amount) "
            "VALUES (:id, :bid, :sid, 'CREDIT', 500)"
        ),
        {"id": uuid.uuid4(), "bid": business.id, "sid": sale.id},
    )
    row = (
        await db_session.execute(
            text("SELECT status, provider FROM payments WHERE sale_id = :sid"), {"sid": sale.id}
        )
    ).one()
    assert row == ("CONFIRMED", "MANUAL")
