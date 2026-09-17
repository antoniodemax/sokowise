"""All ORM models. Importing this package registers every table on `Base.metadata`,
which is what Alembic autogenerate and the test schema checks rely on."""

from app.db.base import Base
from app.models.ai import AIConversation, AIMessage
from app.models.audit import AuditLog
from app.models.business import Business
from app.models.catalog import Category, Product
from app.models.customer import CreditTransaction, Customer
from app.models.expense import Expense
from app.models.inventory import InventoryMovement
from app.models.receipt import Receipt, ReceiptLine
from app.models.sale import Payment, Sale, SaleItem
from app.models.user import BusinessMembership, RefreshToken, User

__all__ = [
    "AIConversation",
    "AIMessage",
    "AuditLog",
    "Base",
    "Business",
    "BusinessMembership",
    "Category",
    "CreditTransaction",
    "Customer",
    "Expense",
    "InventoryMovement",
    "Payment",
    "Product",
    "Receipt",
    "ReceiptLine",
    "RefreshToken",
    "Sale",
    "SaleItem",
    "User",
]
