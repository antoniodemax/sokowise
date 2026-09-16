"""Health endpoints (docs/ARCHITECTURE.md §9).

`/health/live` answers as long as the process runs. `/health/ready` reports whether
the service can serve traffic; until the database is wired in Phase 2 it reports
503 with the reason, exactly as docs/ROADMAP.md Phase 1 specifies.
"""

from http import HTTPStatus
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


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
async def ready(response: Response) -> ReadyResponse:
    # Phase 2 replaces this check with real database connectivity.
    checks = {"database": "not_configured"}
    response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
    return ReadyResponse(status="not_ready", checks=checks)
