"""Shared fixtures.

Phase 1 tests need no database. Database tests (tests/db/) run against a real
PostgreSQL 16 named by TEST_DATABASE_URL and are skipped, visibly, when it is unset.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# Required settings must exist before `app.main` is imported anywhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("LOG_LEVEL", "WARNING")
# A test-only signing key; production refuses to start without a real one.
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret-with-at-least-32-characters")
os.environ.setdefault(
    "DATABASE_URL",
    TEST_DATABASE_URL or "postgresql+asyncpg://sokowise:sokowise@127.0.0.1:5432/sokowise_test",
)

from app.core.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL is not set; see backend/README.md")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def app() -> Iterator[FastAPI]:
    get_settings.cache_clear()
    yield create_app()
    get_settings.cache_clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # raise_server_exceptions=False lets the 500 handler run instead of re-raising in tests.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
