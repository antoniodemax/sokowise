"""Health endpoints (docs/ARCHITECTURE.md §9).

`/health/live` answers as long as the process runs. `/health/ready` reports whether
the service can serve traffic: the database answers and its schema is at the migration
head this build expects. Receipt storage is reported but never fails readiness (a
storage problem must not take the whole API out of rotation), and nothing here touches
the AI provider: SokoWise runs without it.
"""

import logging
from http import HTTPStatus
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.storage import LocalFileStorage

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)


class LiveResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, str]


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={HTTPStatus.SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
)
async def ready(request: Request, response: Response) -> ReadyResponse:
    engine: AsyncEngine = request.app.state.engine
    expected_head: str | None = getattr(request.app.state, "migration_head", None)
    checks: dict[str, str] = {}
    healthy = True
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            checks["database"] = "ok"
            if expected_head is None:
                checks["migrations"] = "unknown"
            else:
                current = list(
                    await connection.scalars(text("SELECT version_num FROM alembic_version"))
                )
                if current == [expected_head]:
                    checks["migrations"] = "ok"
                else:
                    checks["migrations"] = "pending"
                    healthy = False
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.warning(
            "readiness check failed", extra={"check": "database", "error": type(exc).__name__}
        )
        checks["database"] = "unavailable"
        checks.setdefault("migrations", "unknown")
        healthy = False

    storage: LocalFileStorage | None = getattr(request.app.state, "receipt_storage", None)
    if storage is not None:
        checks["receipt_storage"] = "ok" if storage.is_writable() else "unavailable"
        if checks["receipt_storage"] != "ok":
            logger.warning("readiness check degraded", extra={"check": "receipt_storage"})

    if not healthy:
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
        return ReadyResponse(status="not_ready", checks=checks)
    return ReadyResponse(status="ready", checks=checks)
