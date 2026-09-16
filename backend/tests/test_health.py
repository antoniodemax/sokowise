from http import HTTPStatus

from fastapi.testclient import TestClient


def test_live_returns_ok(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}


def test_ready_reports_not_ready_until_database_is_wired(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.json() == {"status": "not_ready", "checks": {"database": "not_configured"}}
