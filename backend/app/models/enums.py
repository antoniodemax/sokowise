"""Enumerated column values (docs/DATA_MAPPING.md).

Stored as VARCHAR with a named CHECK constraint rather than a native Postgres
enum, so adding a value is an ordinary migration (DATA_MAPPING §2).
"""

from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum


class BusinessType(StrEnum):
    GENERAL_SHOP = "GENERAL_SHOP"
    BOUTIQUE = "BOUTIQUE"
    SALON = "SALON"
    RESTAURANT = "RESTAURANT"
    ELECTRONICS = "ELECTRONICS"
    OTHER = "OTHER"


class MembershipRole(StrEnum):
    OWNER = "OWNER"
    STAFF = "STAFF"


class ProductUnit(StrEnum):
    PIECE = "piece"
    KG = "kg"
    G = "g"
    LITRE = "litre"
    ML = "ml"
    METRE = "metre"
    PACK = "pack"
    SERVICE = "service"
    OTHER = "other"


class MovementType(StrEnum):
    INITIAL = "INITIAL"
    RESTOCK = "RESTOCK"
    SALE = "SALE"
    SALE_REVERSAL = "SALE_REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


class SaleStatus(StrEnum):
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class PaymentMethod(StrEnum):
    """Tender on a sale. CREDIT is a receivable, never cash received (PRD BR-15)."""

    CASH = "CASH"
    MPESA = "MPESA"
    CREDIT = "CREDIT"


class PaymentStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    PENDING = "PENDING"
    FAILED = "FAILED"


class PaymentProvider(StrEnum):
    MANUAL = "MANUAL"  # MPESA_DARAJA arrives with the integration (ARCHITECTURE §7)


class CreditEntryType(StrEnum):
    CHARGE = "CHARGE"
    REPAYMENT = "REPAYMENT"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


class MoneyReceivedMethod(StrEnum):
    """How money actually arrived: credit repayments and expenses. No CREDIT here."""

    CASH = "CASH"
    MPESA = "MPESA"


class ReceiptStatus(StrEnum):
    """Supplier receipt lifecycle (docs/DATA_MAPPING.md §3.17)."""

    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReceiptMatchStatus(StrEnum):
    """How a receipt line maps to the catalogue after backend matching."""

    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"


class ReceiptLineReview(StrEnum):
    """The owner's decision on a line at confirmation time."""

    PENDING = "PENDING"
    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"


class MpesaMessageStatus(StrEnum):
    """A pasted M-Pesa confirmation SMS (docs/DATA_MAPPING.md §3.19)."""

    UNPARSED = "UNPARSED"  # kept as raw text so unknown formats are collected during the pilot
    UNMATCHED = "UNMATCHED"  # money received, no sale or repayment carries this code yet
    MATCHED = "MATCHED"  # linked to exactly one payment or one credit repayment
    IGNORED = "IGNORED"  # owner decided it is not shop income (owner-only transition)


class SmsKind(StrEnum):
    """Which M-Pesa product the message came from, inferred from its wording."""

    POCHI = "POCHI"
    TILL = "TILL"
    PAYBILL = "PAYBILL"
    SEND_MONEY = "SEND_MONEY"
    UNKNOWN = "UNKNOWN"


class ProposalStatus(StrEnum):
    """An action the copilot proposed; only the owner's confirm applies it (PRD FR-J7)."""

    PENDING = "PENDING"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AIMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


def enum_column[E: StrEnum](enum_cls: type[E], length: int) -> Enum:
    """VARCHAR(length) column type that stores the enum *values*, with no native type."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        create_constraint=False,
        values_callable=lambda cls: [member.value for member in cls],
    )


def enum_check[E: StrEnum](column: str, enum_cls: type[E], name: str) -> CheckConstraint:
    """Named CHECK constraint restricting `column` to the enum's values."""
    allowed = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)
