from http import HTTPStatus

import pytest
from app.core.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_live_returns_ok(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}


def test_ready_reports_unavailable_when_database_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Port 1 refuses connections immediately; no database is needed for this path.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@127.0.0.1:1/nowhere")
    with TestClient(create_app(Settings())) as client:
        response = client.get("/health/ready")
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "unavailable"
    assert body["checks"]["migrations"] == "unknown"
    assert body["checks"]["receipt_storage"] == "ok"
