"""Shared fixtures. Phase 1 tests need no database."""

import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Required settings must exist before `app.main` is imported anywhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from app.core.config import get_settings
from app.main import create_app


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
