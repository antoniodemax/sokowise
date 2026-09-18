"""Applying a copilot proposal the owner confirmed (PRD FR-J7, ARCHITECTURE §6.4).

The only path from a proposal to a record. It re-validates the confirmed payload from
scratch (the owner may have edited it), checks the proposal is still pending and fresh,
locks the message row, and then calls the same service every screen uses:
`products.create_product`, `sales.create_sale`, `credit.record_repayment`,
`inventory.restock`. Those services own validation, locking, stock and credit rules and
audit rows; this module adds one audit row that ties the record back to the proposal.

Sales and repayments use an idempotency key derived from the message id, so a retried
confirm replays the first result instead of recording twice.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.proposals import (
    ProposalKind,
    ProposeProduct,
    ProposeRepayment,
    ProposeRestock,
    ProposeSale,
    StoredProposal,
    validate_proposal,
)
from app.core.context import BusinessContext, ClientInfo
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.session import transaction
from app.models import AIMessage
from app.models.enums import AIMessageRole, ProposalStatus
from app.repositories import ai as ai_repo
from app.schemas.catalog import ProductCreateRequest
from app.schemas.credit import RepaymentRequest
from app.schemas.inventory import RestockRequest
from app.schemas.sales import PaymentLineRequest, SaleCreateRequest, SaleLineRequest
from app.services import audit, credit, inventory, products, sales
from app.services.audit import AuditAction

logger = logging.getLogger(__name__)

ENTITY_TYPE = "ai_proposal"
# A proposal the owner did not act on for a day is stale: prices and stock may have moved.
PROPOSAL_TTL = timedelta(hours=24)
_IDEMPOTENCY_NAMESPACE = uuid.UUID("2b0a4c1e-8f7d-4e6a-9c3b-1d5e7f9a0b2c")


class ProposalError(AppError):
    status_code = 422
    code = "PROPOSAL_INVALID"


class ProposalStateError(ConflictError):
    code = "PROPOSAL_NOT_PENDING"


class ProposalExpiredError(ConflictError):
    code = "PROPOSAL_EXPIRED"


@dataclass(frozen=True, slots=True)
class Applied:
    message: AIMessage
    kind: ProposalKind
    entity_id: uuid.UUID


async def confirm(
    session: AsyncSession,
    ctx: BusinessContext,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    payload: dict[str, object],
    client: ClientInfo,
) -> Applied:
    """Apply the proposal on `message_id` with the owner's confirmed (maybe edited) payload."""
    message = await _pending_message(session, ctx, conversation_id, message_id)
    stored = StoredProposal.model_validate(message.proposal)
    try:
        parsed = validate_proposal(stored.kind, payload)
    except ValidationError as exc:
        raise ProposalError(
            "The confirmed details are not valid",
            details=[
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
            ][:10],
        ) from None
    edited = parsed.model_dump(mode="json") != stored.payload
    key = uuid.uuid5(_IDEMPOTENCY_NAMESPACE, str(message.id))

    # The record is written by the normal service in its own transaction; only then is the
    # proposal marked applied. A service error leaves the proposal PENDING and retryable.
    if isinstance(parsed, ProposeProduct):
        if parsed.opening_stock is not None and parsed.cost_price is None:
            # An INITIAL movement carries a unit cost (DATA_MAPPING §3.7).
            msg = "Enter the cost price (what you pay per unit) to record the stock you have now"
            raise ProposalError(
                msg, details=[{"loc": ["cost_price"], "msg": msg, "type": "missing"}]
            )
        product = await products.create_product(
            session,
            ctx,
            _request(
                ProductCreateRequest,
                name=parsed.name,
                selling_price=parsed.selling_price,
                cost_price=parsed.cost_price,
                unit=parsed.unit,
                track_inventory=parsed.track_inventory,
                opening_stock=parsed.opening_stock,
            ),
            client,
        )
        entity_id = product.id
    elif isinstance(parsed, ProposeSale):
        created = await sales.create_sale(
            session,
            ctx,
            _request(
                SaleCreateRequest,
                lines=[
                    SaleLineRequest(
                        product_id=line.product_id,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                    )
                    for line in parsed.lines
                ],
                payments=[
                    PaymentLineRequest(method=p.method, amount=p.amount, reference=p.reference)
                    for p in parsed.payments
                ],
                customer_id=parsed.customer_id,
                note=parsed.note,
            ),
            client,
            idempotency_key=key,
        )
        entity_id = created.sale.id
    elif isinstance(parsed, ProposeRepayment):
        posted = await credit.record_repayment(
            session,
            ctx,
            parsed.customer_id,
            _request(
                RepaymentRequest,
                amount=parsed.amount,
                payment_method=parsed.method,
                reference=parsed.reference,
            ),
            client,
            idempotency_key=key,
        )
        entity_id = posted.entry.id
    elif isinstance(parsed, ProposeRestock):
        movement = await inventory.restock(
            session,
            ctx,
            _request(
                RestockRequest,
                product_id=parsed.product_id,
                quantity=parsed.quantity,
                unit_cost=parsed.unit_cost if parsed.unit_cost is not None else Decimal("0"),
                supplier_name=parsed.supplier_name,
            ),
            client,
        )
        entity_id = movement.id
    else:  # pragma: no cover — every kind is handled above
        raise ProposalError("Unknown proposal kind")

    async with transaction(session):
        locked = await _pending_message(session, ctx, conversation_id, message_id, for_update=True)
        locked.proposal_status = ProposalStatus.APPLIED
        locked.proposal_entity_id = entity_id
        locked.proposal_applied_at = datetime.now(UTC)
        await session.flush()
        await audit.record(
            session,
            ctx,
            action=AuditAction.AI_PROPOSAL_APPLY,
            entity_type=ENTITY_TYPE,
            entity_id=locked.id,
            after={"kind": stored.kind.value, "entity_id": str(entity_id), "edited": edited},
            client=client,
        )
    await session.refresh(locked)
    logger.info(
        "ai proposal applied",
        extra={
            "business_id": str(ctx.business_id),
            "message_id": str(locked.id),
            "kind": stored.kind.value,
        },
    )
    return Applied(message=locked, kind=stored.kind, entity_id=entity_id)


async def reject(
    session: AsyncSession,
    ctx: BusinessContext,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    client: ClientInfo,
) -> AIMessage:
    async with transaction(session):
        message = await _pending_message(session, ctx, conversation_id, message_id, for_update=True)
        message.proposal_status = ProposalStatus.REJECTED
        await session.flush()
        stored = StoredProposal.model_validate(message.proposal)
        await audit.record(
            session,
            ctx,
            action=AuditAction.AI_PROPOSAL_REJECT,
            entity_type=ENTITY_TYPE,
            entity_id=message.id,
            after={"kind": stored.kind.value},
            client=client,
        )
    await session.refresh(message)
    return message


def _request[RequestT: BaseModel](model: type[RequestT], **values: object) -> RequestT:
    """Build the normal request schema; its cross-field rules become a 422, never a 500."""
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        raise ProposalError(
            "The confirmed details are not valid",
            details=[
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
            ][:10],
        ) from None


async def _pending_message(
    session: AsyncSession,
    ctx: BusinessContext,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> AIMessage:
    """The assistant message with a PENDING, unexpired proposal, in this user's conversation."""
    conversation = await ai_repo.get_conversation(
        session, business_id=ctx.business_id, user_id=ctx.user_id, conversation_id=conversation_id
    )
    if conversation is None:
        raise NotFoundError("Conversation not found")
    message = await ai_repo.get_message(
        session,
        business_id=ctx.business_id,
        conversation_id=conversation.id,
        message_id=message_id,
        for_update=for_update,
    )
    if message is None or message.role is not AIMessageRole.ASSISTANT or message.proposal is None:
        raise NotFoundError("Proposal not found")
    if message.proposal_status is not ProposalStatus.PENDING:
        raise ProposalStateError(
            f"This proposal was already {message.proposal_status.value.lower()}"
            if message.proposal_status
            else "This proposal is not pending"
        )
    if datetime.now(UTC) - message.created_at > PROPOSAL_TTL:
        raise ProposalExpiredError("This proposal is more than a day old. Ask the copilot again.")
    return message


__all__ = [
    "PROPOSAL_TTL",
    "Applied",
    "ProposalError",
    "ProposalExpiredError",
    "ProposalStateError",
    "confirm",
    "reject",
]
