"""Readiness against the real database."""

from http import HTTPStatus

import pytest
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db


def test_ready_is_200_when_the_database_answers(migrated_database: str) -> None:
    settings = Settings(database_url=migrated_database)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}
