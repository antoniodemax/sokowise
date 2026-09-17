"""Errors the copilot reports through the standard envelope (docs/ARCHITECTURE.md §8)."""

from http import HTTPStatus

from app.core.errors import AppError


class AINotConfiguredError(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "AI_NOT_CONFIGURED"


class AIUnavailableError(AppError):
    """The provider timed out, failed or answered something we refuse to relay."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "AI_UNAVAILABLE"


class AIQuotaExceededError(AppError):
    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "AI_QUOTA_EXCEEDED"
