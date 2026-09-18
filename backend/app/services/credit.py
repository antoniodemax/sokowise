"""The customer credit ledger (PRD FR-G2-G5, BR-7, BR-8; DATA_MAPPING §3.12).

Accounting model — one convention, used by every writer:

    balance = Σ credit_transactions.amount            (signed; PRD BR-7)
    CHARGE      +amount   a credit sale (sales phase)
    REPAYMENT   -amount   money received, CASH or MPESA
    REVERSAL    -amount   a voided credit sale (sales phase)
    ADJUSTMENT  ±amount   owner correction, reason required

`post_entry` is the only way a row gets into the ledger. It runs under the customer
row lock (`get_customer_for_update`), computes `balance_after` from the locked
cache, moves `customers.balance` and inserts the row — one transaction, so the
cache can never disagree with the ledger and two concurrent writers serialise.
`repositories.credit.sum_entries` recomputes the same number from the rows for
verification.

Negative balances: BR-7 allows "credit in favour" when a customer over-repays, but
never by accident — a repayment beyond the debt needs `allow_overpayment`, and an
adjustment can never push the balance below zero (a REVERSAL may, BR-8).

Idempotency (same pattern as sales): repayments and adjustments may carry an
`Idempotency-Key`. Same key + same payload → the original entry, unchanged; same
key + different payload → 409 `IDEMPOTENCY_CONFLICT`.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import BusinessContext, ClientInfo
from app.core.errors import ConflictError, NotFoundError
from app.db.session import transaction
from app.models import CreditTransaction, Customer
from app.models.enums import CreditEntryType, MembershipRole, MoneyReceivedMethod
from app.repositories import credit as credit_repo
from app.repositories import customers as customer_repo
from app.repositories.credit import DebtorRow, DebtorSort
from app.schemas.credit import AdjustmentDirection, AdjustmentRequest, RepaymentRequest
from app.services import audit
from app.services.audit import AuditAction

logger = logging.getLogger(__name__)

ENTITY_TYPE = "customer"
CENT = Decimal("0.01")
_IDEMPOTENCY_INDEX = "uq_credit_transactions_business_id_idempotency_key"


class NegativeBalanceError(ConflictError):
    """The entry would take the balance below zero and the caller did not allow that."""

    code = "BALANCE_WOULD_BE_NEGATIVE"


class CreditLimitExceededError(ConflictError):
    code = "CREDIT_LIMIT_EXCEEDED"


class IdempotencyConflictError(ConflictError):
    code = "IDEMPOTENCY_CONFLICT"


@dataclass(frozen=True, slots=True)
class Posted:
    """A ledger write: the entry and whether it was newly created (False = idempotent replay)."""

    entry: CreditTransaction
    created: bool


# --- the one write path --------------------------------------------------------------------


async def post_entry(
    session: AsyncSession,
    ctx: BusinessContext,
    *,
    customer: Customer,
    entry_type: CreditEntryType,
    amount: Decimal,
    allow_negative: bool = False,
    negative_error_code: str = NegativeBalanceError.code,
    payment_method: MoneyReceivedMethod | None = None,
    reference: str | None = None,
    reason: str | None = None,
    sale_id: uuid.UUID | None = None,
    payment_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
    idempotency_key: uuid.UUID | None = None,
    idempotency_hash: str | None = None,
) -> CreditTransaction:
    """Append one ledger row and move the cache. `customer` must be locked (FOR UPDATE).

    `amount` is the signed effect on the balance. The caller owns the transaction.
    """
    if customer.business_id != ctx.business_id:  # pragma: no cover — repositories scope
        msg = "customer does not belong to the business context"
        raise RuntimeError(msg)
    amount = amount.quantize(CENT)
    if amount == 0:
        msg = "a ledger entry must move the balance"
        raise ValueError(msg)
    balance_after = (customer.balance + amount).quantize(CENT)
    if balance_after < 0 and not allow_negative:
        raise NegativeBalanceError(
            "This would take the customer's balance below zero", code=negative_error_code
        )
    customer.balance = balance_after
    entry = CreditTransaction(
        business_id=ctx.business_id,
        customer_id=customer.id,
        entry_type=entry_type,
        amount=amount,
        balance_after=balance_after,
        sale_id=sale_id,
        payment_id=payment_id,
        payment_method=payment_method,
        reference=reference,
        reason=reason,
        idempotency_key=idempotency_key,
        idempotency_hash=idempotency_hash,
        occurred_at=occurred_at or datetime.now(UTC),
        created_by=ctx.user_id,
    )
    return await credit_repo.add_entry(session, entry)


# --- idempotency -----------------------------------------------------------------------


def payload_hash(operation: str, customer_id: uuid.UUID, payload: dict[str, object]) -> str:
    canonical = json.dumps(
        {"op": operation, "customer_id": str(customer_id), "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _replay(
    session: AsyncSession, ctx: BusinessContext, key: uuid.UUID | None, digest: str | None
) -> CreditTransaction | None:
    """The entry an earlier request with this key created, or None. Different payload → 409."""
    if key is None:
        return None
    existing = await credit_repo.get_entry_by_idempotency_key(
        session, business_id=ctx.business_id, idempotency_key=key
    )
    if existing is None:
        return None
    if existing.idempotency_hash != digest:
        raise IdempotencyConflictError(
            "This Idempotency-Key was already used with a different request"
        )
    return existing


async def _locked_customer(
    session: AsyncSession, ctx: BusinessContext, customer_id: uuid.UUID
) -> Customer:
    customer = await customer_repo.get_customer_for_update(
        session, business_id=ctx.business_id, customer_id=customer_id
    )
    if customer is None:
        raise NotFoundError("Customer not found")
    return customer


# --- operations ---------------------------------------------------------------------


async def record_repayment(
    session: AsyncSession,
    ctx: BusinessContext,
    customer_id: uuid.UUID,
    data: RepaymentRequest,
    client: ClientInfo,
    *,
    idempotency_key: uuid.UUID | None = None,
) -> Posted:
    """A repayment against the customer, not a sale (PRD FR-G3). OWNER and STAFF."""
    digest = (
        payload_hash("repayment", customer_id, data.model_dump(mode="json"))
        if idempotency_key
        else None
    )
    try:
        async with transaction(session):
            customer = await _locked_customer(session, ctx, customer_id)
            replay = await _replay(session, ctx, idempotency_key, digest)
            if replay is not None:
                return Posted(entry=replay, created=False)
            entry = await post_entry(
                session,
                ctx,
                customer=customer,
                entry_type=CreditEntryType.REPAYMENT,
                amount=-data.amount,
                allow_negative=data.allow_overpayment,
                negative_error_code="REPAYMENT_EXCEEDS_BALANCE",
                payment_method=data.payment_method,
                reference=data.reference,
                idempotency_key=idempotency_key,
                idempotency_hash=digest,
            )
            if data.payment_method is MoneyReceivedMethod.MPESA and data.reference:
                # A pasted M-Pesa message with this code gets linked (ARCHITECTURE §7).
                from app.services import mpesa  # local: mpesa imports this module

                await mpesa.link_reference_in_transaction(
                    session,
                    ctx,
                    reference=data.reference,
                    credit_transaction_id=entry.id,
                    via="credit.repayment",
                    client=client,
                )
            await audit.record(
                session,
                ctx,
                action=AuditAction.CREDIT_REPAYMENT,
                entity_type=ENTITY_TYPE,
                entity_id=customer.id,
                after={
                    "entry_id": str(entry.id),
                    "amount": str(-entry.amount),
                    "payment_method": data.payment_method.value,
                    "balance_after": str(entry.balance_after),
                },
                client=client,
            )
    except IntegrityError as exc:
        if _IDEMPOTENCY_INDEX in str(exc.orig):
            raise IdempotencyConflictError(
                "This Idempotency-Key was already used with a different request"
            ) from None
        raise
    logger.info(
        "repayment recorded",
        extra={"business_id": str(ctx.business_id), "entry_id": str(entry.id)},
    )
    return Posted(entry=entry, created=True)


async def record_adjustment(
    session: AsyncSession,
    ctx: BusinessContext,
    customer_id: uuid.UUID,
    data: AdjustmentRequest,
    client: ClientInfo,
    *,
    idempotency_key: uuid.UUID | None = None,
) -> Posted:
    """An owner's correction with a reason (PRD FR-G2). Cannot take the balance below zero."""
    signed = data.amount if data.direction is AdjustmentDirection.INCREASE else -data.amount
    digest = (
        payload_hash("adjustment", customer_id, data.model_dump(mode="json"))
        if idempotency_key
        else None
    )
    try:
        async with transaction(session):
            customer = await _locked_customer(session, ctx, customer_id)
            replay = await _replay(session, ctx, idempotency_key, digest)
            if replay is not None:
                return Posted(entry=replay, created=False)
            entry = await post_entry(
                session,
                ctx,
                customer=customer,
                entry_type=CreditEntryType.ADJUSTMENT,
                amount=signed,
                negative_error_code="ADJUSTMENT_EXCEEDS_BALANCE",
                reason=data.reason,
                idempotency_key=idempotency_key,
                idempotency_hash=digest,
            )
            await audit.record(
                session,
                ctx,
                action=AuditAction.CREDIT_ADJUST,
                entity_type=ENTITY_TYPE,
                entity_id=customer.id,
                before={"balance": str(entry.balance_after - entry.amount)},
                after={
                    "entry_id": str(entry.id),
                    "amount": str(entry.amount),
                    "reason": data.reason,
                    "balance": str(entry.balance_after),
                },
                client=client,
            )
    except IntegrityError as exc:
        if _IDEMPOTENCY_INDEX in str(exc.orig):
            raise IdempotencyConflictError(
                "This Idempotency-Key was already used with a different request"
            ) from None
        raise
    logger.info(
        "adjustment recorded",
        extra={"business_id": str(ctx.business_id), "entry_id": str(entry.id)},
    )
    return Posted(entry=entry, created=True)


async def get_ledger(
    session: AsyncSession, ctx: BusinessContext, customer_id: uuid.UUID, *, limit: int
) -> tuple[Customer, list[CreditTransaction]]:
    customer = await customer_repo.get_customer(
        session, business_id=ctx.business_id, customer_id=customer_id
    )
    if customer is None:
        raise NotFoundError("Customer not found")
    entries = await credit_repo.list_entries(
        session, business_id=ctx.business_id, customer_id=customer.id, limit=limit
    )
    return customer, entries


async def list_debtors(
    session: AsyncSession, ctx: BusinessContext, *, sort: DebtorSort, limit: int
) -> list[DebtorRow]:
    return await credit_repo.list_debtors(session, ctx.business_id, sort=sort, limit=limit)


# --- credit limit (PRD FR-G5) ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreditLimitCheck:
    balance: Decimal
    credit_limit: Decimal | None  # None = no limit
    projected_balance: Decimal
    exceeded: bool


def evaluate_credit_limit(customer: Customer, additional_charge: Decimal) -> CreditLimitCheck:
    """Would charging `additional_charge` more leave the customer over their limit?

    `credit_limit` NULL = unlimited (DATA_MAPPING §3.8); 0 = no credit at all. Exactly at
    the limit is allowed.
    """
    projected = (customer.balance + additional_charge).quantize(CENT)
    exceeded = customer.credit_limit is not None and projected > customer.credit_limit
    return CreditLimitCheck(
        balance=customer.balance,
        credit_limit=customer.credit_limit,
        projected_balance=projected,
        exceeded=exceeded,
    )


def enforce_credit_limit(
    customer: Customer,
    additional_charge: Decimal,
    *,
    role: MembershipRole,
    owner_override: bool = False,
) -> CreditLimitCheck:
    """FR-G5: over the limit, STAFF is blocked; OWNER is warned and may proceed.

    The "warning" is this 409 `CREDIT_LIMIT_EXCEEDED`; an OWNER proceeds by repeating
    the request with `owner_override=True`. The sales phase wires the flag; nothing in
    Phase 7 charges a customer, so this is only the reusable primitive.
    """
    check = evaluate_credit_limit(customer, additional_charge)
    if check.exceeded and not (role is MembershipRole.OWNER and owner_override):
        raise CreditLimitExceededError(
            "This would exceed the customer's credit limit",
            details={
                "balance": str(check.balance),
                "credit_limit": str(check.credit_limit),
                "projected_balance": str(check.projected_balance),
                "owner_may_override": role is MembershipRole.OWNER,
            },
        )
    return check


@dataclass(frozen=True, slots=True)
class BalanceDiscrepancy:
    customer_id: uuid.UUID
    cached_balance: Decimal
    ledger_balance: Decimal
    repaired: bool


@dataclass(frozen=True, slots=True)
class BalanceRecomputeResult:
    customers_checked: int
    discrepancies: list[BalanceDiscrepancy]
    applied: bool


async def recompute_balances(
    session: AsyncSession, ctx: BusinessContext, *, apply: bool, client: ClientInfo | None = None
) -> BalanceRecomputeResult:
    """Compare every customer's cached balance with Σ ledger; rewrite it when `apply`.

    The ledger is the truth (PRD BR-7). Each customer is locked before its ledger sum is
    read, exactly like `post_entry`, so a concurrent repayment cannot slip between the
    comparison and the repair. A repair writes no ledger entry and is audited
    (`credit.recompute`); a dry run (`apply=False`) changes nothing.
    """
    discrepancies: list[BalanceDiscrepancy] = []
    async with transaction(session):
        customer_ids = await customer_repo.list_customer_ids(session, ctx.business_id)
        for customer_id in customer_ids:
            customer = await customer_repo.get_customer_for_update(
                session, business_id=ctx.business_id, customer_id=customer_id
            )
            if customer is None:  # pragma: no cover — listed a moment ago
                continue
            ledger = await credit_repo.sum_entries(
                session, business_id=ctx.business_id, customer_id=customer_id
            )
            cached = customer.balance.quantize(Decimal("0.01"))
            if cached == ledger:
                continue
            if apply:
                customer.balance = ledger
                await session.flush()
                await audit.record(
                    session,
                    ctx,
                    action=AuditAction.CREDIT_RECOMPUTE,
                    entity_type=ENTITY_TYPE,
                    entity_id=customer.id,
                    before={"balance": str(cached)},
                    after={"balance": str(ledger)},
                    client=client,
                )
            discrepancies.append(
                BalanceDiscrepancy(
                    customer_id=customer_id,
                    cached_balance=cached,
                    ledger_balance=ledger,
                    repaired=apply,
                )
            )
    return BalanceRecomputeResult(
        customers_checked=len(customer_ids), discrepancies=discrepancies, applied=apply
    )
