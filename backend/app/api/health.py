"""Health endpoints (docs/ARCHITECTURE.md §9).

`/health/live` answers as long as the process runs. `/health/ready` reports whether
the service can serve traffic, which since Phase 2 means the database answers.
"""

import logging
from http import HTTPStatus
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

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
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.warning(
            "readiness check failed", extra={"check": "database", "error": type(exc).__name__}
        )
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
        return ReadyResponse(status="not_ready", checks={"database": "unavailable"})
    return ReadyResponse(status="ready", checks={"database": "ok"})
