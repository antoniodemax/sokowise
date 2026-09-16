"""Versioned API routers, mounted at `/api/v1`."""

from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.auth import router as auth_router
from app.api.v1.business import router as business_router
from app.api.v1.categories import router as categories_router
from app.api.v1.customers import router as customers_router
from app.api.v1.debtors import router as debtors_router
from app.api.v1.expenses import router as expenses_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.products import router as products_router
from app.api.v1.sales import router as sales_router
from app.api.v1.users import router as users_router

router = APIRouter(prefix="/api/v1")
router.include_router(auth_router)
router.include_router(business_router)
router.include_router(users_router)
router.include_router(categories_router)
router.include_router(products_router)
router.include_router(customers_router)
router.include_router(debtors_router)
router.include_router(sales_router)
router.include_router(inventory_router)
router.include_router(analytics_router)
router.include_router(expenses_router)
