"""Application factory, settings and request-ID behaviour."""

import uuid
from http import HTTPStatus

import pytest
from app.core.config import Settings
from app.main import create_app
from app.middleware.request_id import REQUEST_ID_HEADER, resolve_request_id
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError


def test_create_app_builds_a_fastapi_instance(app: FastAPI) -> None:
    assert isinstance(app, FastAPI)
    assert app.title == "SokoWise API"


def test_settings_fail_fast_when_required_values_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    missing = {str(error["loc"][0]) for error in exc_info.value.errors()}
    assert missing == {"app_env", "cors_origins"}


def test_settings_split_comma_separated_cors_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


def test_production_settings_disable_interactive_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    prod_app = create_app(Settings())
    with TestClient(prod_app) as client:
        assert client.get("/docs").status_code == HTTPStatus.NOT_FOUND
        assert client.get("/openapi.json").status_code == HTTPStatus.NOT_FOUND


def test_response_carries_a_generated_request_id(client: TestClient) -> None:
    response = client.get("/health/live")
    request_id = response.headers[REQUEST_ID_HEADER]
    uuid.UUID(request_id)  # generated IDs are UUIDs


def test_valid_client_request_id_is_preserved(client: TestClient) -> None:
    response = client.get("/health/live", headers={REQUEST_ID_HEADER: "client-abc.123"})
    assert response.headers[REQUEST_ID_HEADER] == "client-abc.123"


@pytest.mark.parametrize("candidate", ["", "has space", "x" * 65, "bad\nline", "<script>"])
def test_unsafe_client_request_id_is_replaced(candidate: str) -> None:
    resolved = resolve_request_id(candidate)
    assert resolved != candidate
    uuid.UUID(resolved)
