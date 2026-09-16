"""The error envelope must be identical for every failure path."""

from http import HTTPStatus

from app.core.errors import AppError
from app.middleware.request_id import REQUEST_ID_HEADER
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


class TeapotError(AppError):
    status_code = HTTPStatus.IM_A_TEAPOT
    code = "TEAPOT"


def _mount_probe_routes(app: FastAPI) -> None:
    """Throwaway routes that exercise each failure path; not part of the real API."""
    router = APIRouter(prefix="/_probe")

    @router.get("/validate")
    async def validate(limit: int) -> dict[str, int]:
        return {"limit": limit}

    @router.get("/app-error")
    async def app_error() -> None:
        raise TeapotError("short and stout", details={"hint": "tip me over"})

    @router.get("/crash")
    async def crash() -> None:
        raise RuntimeError("secret internal detail: db password is hunter2")

    app.include_router(router)


def _assert_envelope(body: dict[str, object], *, code: str, request_id: str) -> dict[str, object]:
    assert set(body) == {"error"}
    error = body["error"]
    assert isinstance(error, dict)
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == code
    assert error["request_id"] == request_id
    return error


def test_validation_error_uses_envelope_with_field_details(app: FastAPI) -> None:
    _mount_probe_routes(app)
    with TestClient(app) as client:
        response = client.get("/_probe/validate", params={"limit": "not-a-number"})
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    error = _assert_envelope(
        response.json(), code="VALIDATION_ERROR", request_id=response.headers[REQUEST_ID_HEADER]
    )
    details = error["details"]
    assert isinstance(details, list) and details[0]["loc"] == ["query", "limit"]


def test_app_error_maps_status_code_message_and_details(app: FastAPI) -> None:
    _mount_probe_routes(app)
    with TestClient(app) as client:
        response = client.get("/_probe/app-error")
    assert response.status_code == HTTPStatus.IM_A_TEAPOT
    error = _assert_envelope(
        response.json(), code="TEAPOT", request_id=response.headers[REQUEST_ID_HEADER]
    )
    assert error["message"] == "short and stout"
    assert error["details"] == {"hint": "tip me over"}


def test_unknown_route_uses_envelope(client: TestClient) -> None:
    response = client.get("/no-such-route")
    assert response.status_code == HTTPStatus.NOT_FOUND
    _assert_envelope(
        response.json(), code="NOT_FOUND", request_id=response.headers[REQUEST_ID_HEADER]
    )


def test_unhandled_exception_hides_internals(app: FastAPI) -> None:
    _mount_probe_routes(app)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_probe/crash")
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    error = _assert_envelope(
        response.json(), code="INTERNAL_ERROR", request_id=response.headers[REQUEST_ID_HEADER]
    )
    assert error["message"] == "An unexpected error occurred"
    assert "hunter2" not in response.text
    assert "Traceback" not in response.text


def test_error_envelope_still_carries_cors_headers(app: FastAPI) -> None:
    """The request-ID layer sits inside CORS, so browsers can read error responses."""
    _mount_probe_routes(app)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_probe/crash", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert REQUEST_ID_HEADER in response.headers
