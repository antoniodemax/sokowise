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
