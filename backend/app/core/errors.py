"""Error envelope and exception handlers (docs/ARCHITECTURE.md §8).

Every non-2xx response has the shape:

    {"error": {"code": "...", "message": "...", "details": ..., "request_id": "..."}}

Domain exceptions raised by services subclass `AppError`; this module only maps
them to HTTP. Stack traces, SQL and internal identifiers never reach the client.
"""

import logging
from http import HTTPStatus

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for errors the API reports deliberately.

    `code` is a stable, machine-readable identifier; `message` is safe to show a user.
    """

    status_code: int = HTTPStatus.BAD_REQUEST
    code: str = "BAD_REQUEST"
    # Extra response headers, e.g. `WWW-Authenticate` on 401 or `Retry-After` on 429.
    headers: dict[str, str] | None = None

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: object = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code is not None:
            self.code = code
        if headers is not None:
            self.headers = headers


class UnauthorizedError(AppError):
    """Missing, invalid or expired credentials. The message never says which."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "UNAUTHORIZED"
    headers = {"WWW-Authenticate": "Bearer"}


class PermissionDeniedError(AppError):
    """Authenticated, but not allowed to do this within the caller's own business."""

    status_code = HTTPStatus.FORBIDDEN
    code = "FORBIDDEN"


class NotFoundError(AppError):
    """Also the answer for anything belonging to another business (ARCHITECTURE §8)."""

    status_code = HTTPStatus.NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = HTTPStatus.CONFLICT
    code = "CONFLICT"


class RateLimitedError(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "RATE_LIMITED"

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message, headers={"Retry-After": str(retry_after_seconds)})


def error_response(
    *, status_code: int, code: str, message: str, details: object = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": request_id_var.get(),
            }
        },
    )


# Codes for the framework-level HTTP errors that can occur before any service runs.
_HTTP_STATUS_CODES: dict[int, str] = {
    HTTPStatus.BAD_REQUEST: "BAD_REQUEST",
    HTTPStatus.UNAUTHORIZED: "UNAUTHORIZED",
    HTTPStatus.FORBIDDEN: "FORBIDDEN",
    HTTPStatus.NOT_FOUND: "NOT_FOUND",
    HTTPStatus.METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    HTTPStatus.CONFLICT: "CONFLICT",
    HTTPStatus.UNPROCESSABLE_ENTITY: "VALIDATION_ERROR",
    HTTPStatus.TOO_MANY_REQUESTS: "RATE_LIMITED",
    HTTPStatus.SERVICE_UNAVAILABLE: "SERVICE_UNAVAILABLE",
}


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 — registered only for AppError
    response = error_response(
        status_code=exc.status_code, code=exc.code, message=exc.message, details=exc.details
    )
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    details = [
        {
            "loc": [str(part) for part in error.get("loc", ())],
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    return error_response(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details=details,
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    status = exc.status_code
    code = _HTTP_STATUS_CODES.get(status, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(status).phrase
    response = error_response(status_code=status, code=code, message=message)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled exception", extra={"path": request.url.path})
    sentry_sdk.capture_exception(exc)  # no-op unless Sentry is initialised; de-duplicated
    return error_response(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
