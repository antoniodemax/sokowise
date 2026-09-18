"""Actions the copilot may *propose* (PRD FR-J7, ARCHITECTURE §6.4).

A proposal is data the model returned through a `propose_*` tool call. It is validated
here, stored on the assistant message, shown to the owner, and applied only by
`services.ai_actions.confirm` with the payload the owner confirmed (possibly edited),
through the same services and validation every screen uses. The model never writes.

Ids inside a proposal come from the read tools (`search_products`, `search_customers`)
and are re-checked against the caller's business at confirm time, so a hallucinated or
foreign id can never act.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import MoneyReceivedMethod, PaymentMethod, ProductUnit

Money = Annotated[Decimal, Field(max_digits=14, decimal_places=2, ge=0)]
PositiveMoney = Annotated[Decimal, Field(max_digits=14, decimal_places=2, gt=0)]
Quantity = Annotated[Decimal, Field(max_digits=12, decimal_places=3, gt=0)]


class ProposalKind(StrEnum):
    PRODUCT = "product"
    SALE = "sale"
    REPAYMENT = "repayment"
    RESTOCK = "restock"


class ProposeProduct(BaseModel):
    """A new product. The owner edits the fields before confirming."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    selling_price: Money
    cost_price: Money | None = None
    unit: ProductUnit = ProductUnit.PIECE
    track_inventory: bool = True
    opening_stock: Quantity | None = None


class ProposedSaleLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    quantity: Quantity
    unit_price: Money | None = None


class ProposedPayment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    method: PaymentMethod
    amount: PositiveMoney
    reference: str | None = Field(default=None, max_length=64)


class ProposeSale(BaseModel):
    """A sale. Lines name products by id from `search_products`; payments must add up."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    lines: list[ProposedSaleLine] = Field(min_length=1, max_length=30)
    payments: list[ProposedPayment] = Field(min_length=1, max_length=5)
    customer_id: UUID | None = None
    note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def credit_needs_customer(self) -> "ProposeSale":
        if (
            any(p.method is PaymentMethod.CREDIT for p in self.payments)
            and self.customer_id is None
        ):
            msg = "A credit sale needs a customer"
            raise ValueError(msg)
        return self


class ProposeRepayment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    customer_id: UUID
    amount: PositiveMoney
    method: MoneyReceivedMethod
    reference: str | None = Field(default=None, max_length=64)


class ProposeRestock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_id: UUID
    quantity: Quantity
    unit_cost: Money | None = None
    supplier_name: str | None = Field(default=None, max_length=120)


PROPOSAL_MODELS: dict[ProposalKind, type[BaseModel]] = {
    ProposalKind.PRODUCT: ProposeProduct,
    ProposalKind.SALE: ProposeSale,
    ProposalKind.REPAYMENT: ProposeRepayment,
    ProposalKind.RESTOCK: ProposeRestock,
}

# Tool name → proposal kind. Only these names are proposals; everything else is a read tool.
PROPOSAL_TOOLS: dict[str, ProposalKind] = {
    "propose_product": ProposalKind.PRODUCT,
    "propose_sale": ProposalKind.SALE,
    "propose_repayment": ProposalKind.REPAYMENT,
    "propose_restock": ProposalKind.RESTOCK,
}

PROPOSAL_DESCRIPTIONS: dict[str, str] = {
    "propose_product": (
        "Propose adding a NEW product for the owner to confirm. Use when the owner asks to add,"
        " create or start selling an item that search_products does not find. Give the price in"
        " KSh as a number. The product is NOT created until the owner confirms."
    ),
    "propose_sale": (
        "Propose recording a sale for the owner to confirm. First resolve every item with"
        " search_products and use the returned product_id; ask the owner if an item is not"
        " found. payments must add up to the sale total (quantity times unit_price, using the"
        " product's selling_price unless the owner gave another price). CREDIT needs a"
        " customer_id from search_customers. Nothing is recorded until the owner confirms."
    ),
    "propose_repayment": (
        "Propose recording money a customer paid against their debt (deni), for the owner to"
        " confirm. Resolve the customer with search_customers first. Not a sale."
    ),
    "propose_restock": (
        "Propose adding stock the owner bought (a restock), for the owner to confirm. Resolve"
        " the product with search_products first. Restocks are stock-in, never expenses."
    ),
}


class StoredProposal(BaseModel):
    """What sits in `ai_messages.proposal`."""

    model_config = ConfigDict(extra="forbid")

    kind: ProposalKind
    payload: dict[str, object]


def validate_proposal(kind: ProposalKind, payload: object) -> BaseModel:
    """Parse a payload with the kind's schema; raises pydantic.ValidationError."""
    return PROPOSAL_MODELS[kind].model_validate(payload)


__all__ = [
    "PROPOSAL_DESCRIPTIONS",
    "PROPOSAL_MODELS",
    "PROPOSAL_TOOLS",
    "ProposalKind",
    "ProposeProduct",
    "ProposeRepayment",
    "ProposeRestock",
    "ProposeSale",
    "StoredProposal",
    "validate_proposal",
]
