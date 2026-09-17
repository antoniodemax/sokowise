"""CSRF protection and cookie attributes (ARCHITECTURE §5.1)."""

from http import HTTPStatus

import pytest
from app.api.deps import CSRF_HEADER
from httpx import AsyncClient

from tests.db.auth_helpers import (
    CSRF_HEADERS,
    LOGIN_URL,
    LOGOUT_URL,
    ME_URL,
    PASSWORD,
    REFRESH_URL,
    REGISTER_URL,
    bearer,
    error_code,
    refresh_cookie,
    register,
    register_payload,
)
from tests.db.conftest import ApiFactory

pytestmark = [pytest.mark.db, pytest.mark.anyio]

ALLOWED_ORIGIN = "http://localhost:5173"  # CORS_ORIGINS in tests/conftest.py
EVIL_ORIGIN = "https://evil.example"


async def test_refresh_with_header_and_allowed_origin_succeeds(api: AsyncClient) -> None:
    await register(api)
    response = await api.post(REFRESH_URL, headers={**CSRF_HEADERS, "Origin": ALLOWED_ORIGIN})
    assert response.status_code == HTTPStatus.OK


async def test_refresh_without_the_custom_header_is_rejected(api: AsyncClient) -> None:
    await register(api)
    cookie = refresh_cookie(api)
    response = await api.post(REFRESH_URL, headers={"Origin": ALLOWED_ORIGIN})
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert error_code(response) == "CSRF_REJECTED"
    assert refresh_cookie(api) == cookie  # nothing consumed, nothing rotated


@pytest.mark.parametrize("value", ["", "XMLHttpRequest", "SokoWise", "sokowise "])
async def test_wrong_header_value_is_rejected(api: AsyncClient, value: str) -> None:
    await register(api)
    response = await api.post(REFRESH_URL, headers={CSRF_HEADER: value})
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.parametrize("origin", [EVIL_ORIGIN, "null", "http://localhost:5173.evil.example"])
async def test_cookie_endpoints_reject_foreign_origins(api: AsyncClient, origin: str) -> None:
    await register(api)
    for url in (REFRESH_URL, LOGOUT_URL):
        response = await api.post(url, headers={**CSRF_HEADERS, "Origin": origin})
        assert response.status_code == HTTPStatus.FORBIDDEN, (url, origin)
        assert error_code(response) == "CSRF_REJECTED"


async def test_login_and_register_reject_foreign_origins(api: AsyncClient) -> None:
    """Login CSRF: a foreign page must not be able to log the victim into an attacker's account."""
    response = await api.post(
        REGISTER_URL, json=register_payload(), headers={"Origin": EVIL_ORIGIN}
    )
    assert response.status_code == HTTPStatus.FORBIDDEN
    response = await api.post(
        LOGIN_URL,
        json={"identifier": "+254700888111", "password": PASSWORD},
        headers={"Origin": EVIL_ORIGIN},
    )
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert refresh_cookie(api) is None


async def test_bearer_endpoints_do_not_need_the_csrf_header(api: AsyncClient) -> None:
    """A bearer token is not an ambient credential; a foreign page cannot attach it."""
    token = (await register(api)).json()["access_token"]
    assert (await api.get(ME_URL, headers=bearer(token))).status_code == HTTPStatus.OK


async def test_get_requests_carry_no_cookie_and_change_nothing(api: AsyncClient) -> None:
    await register(api)
    response = await api.get(REFRESH_URL, headers={"Origin": EVIL_ORIGIN})
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert refresh_cookie(api) is not None


async def test_dev_origin_configured_with_a_trailing_slash_still_passes_the_origin_check(
    api_factory: ApiFactory,
) -> None:
    """Regression: `CORS_ORIGINS=http://localhost:5173/` (trailing slash) made every browser
    auth POST a 403 CSRF_REJECTED, because browsers send `Origin: http://localhost:5173`.
    The guard itself is unchanged; the configured value is normalised."""
    api = await api_factory(cors_origins=["http://localhost:5173/"])
    browser_origin = {"Origin": "http://localhost:5173"}
    # Login: past the origin check → the credential outcome (401), never 403.
    login = await api.post(
        LOGIN_URL,
        json={"identifier": "nobody@example.test", "password": "x"},
        headers=browser_origin,
    )
    assert login.status_code == HTTPStatus.UNAUTHORIZED, login.text
    assert error_code(login) == "INVALID_CREDENTIALS"
    # Refresh without a cookie: past the origin and header checks → 401, never 403.
    refresh = await api.post(REFRESH_URL, headers={**CSRF_HEADERS, **browser_origin})
    assert refresh.status_code == HTTPStatus.UNAUTHORIZED, refresh.text
    # Foreign origins are still rejected: normalisation widened nothing.
    evil = await api.post(REFRESH_URL, headers={**CSRF_HEADERS, "Origin": EVIL_ORIGIN})
    assert evil.status_code == HTTPStatus.FORBIDDEN and error_code(evil) == "CSRF_REJECTED"


async def test_preview_origins_can_be_allowed_by_regex(api_factory: ApiFactory) -> None:
    api = await api_factory(cors_origin_regex=r"https://sokowise-[a-z0-9-]+\.vercel\.app")
    await register(api)
    preview = "https://sokowise-git-feature-x-team.vercel.app"
    ok = await api.post(REFRESH_URL, headers={**CSRF_HEADERS, "Origin": preview})
    assert ok.status_code == HTTPStatus.OK
    assert ok.headers["access-control-allow-origin"] == preview
    assert ok.headers["access-control-allow-credentials"] == "true"
    bad = await api.post(
        REFRESH_URL,
        headers={**CSRF_HEADERS, "Origin": "https://sokowise-x.vercel.app.evil.example"},
    )
    assert bad.status_code == HTTPStatus.FORBIDDEN


async def test_preflight_for_the_custom_header_passes_only_for_allowed_origins(
    api: AsyncClient,
) -> None:
    allowed = await api.options(
        REFRESH_URL,
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": CSRF_HEADER,
        },
    )
    assert allowed.status_code == HTTPStatus.OK
    assert allowed.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    denied = await api.options(
        REFRESH_URL,
        headers={
            "Origin": EVIL_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": CSRF_HEADER,
        },
    )
    assert "access-control-allow-origin" not in denied.headers


# --- cookie attributes per environment ---------------------------------------------


def _set_cookie(response_headers: object, api: AsyncClient) -> str:
    return str(response_headers).lower()


async def test_production_style_cookie_attributes(api_factory: ApiFactory) -> None:
    api = await api_factory(
        cookie_secure=True, cookie_samesite="lax", cookie_domain="api.sokowise.test"
    )
    response = await register(api)
    header = response.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "secure" in header
    assert "samesite=lax" in header
    assert "domain=api.sokowise.test" in header
    assert "path=/api/v1/auth" in header


async def test_cross_site_preview_cookie_attributes(api_factory: ApiFactory) -> None:
    api = await api_factory(cookie_secure=True, cookie_samesite="none")
    response = await register(api)
    header = response.headers["set-cookie"].lower()
    assert "samesite=none" in header and "secure" in header and "httponly" in header


async def test_development_cookie_can_drop_secure_only_outside_production(
    api_factory: ApiFactory,
) -> None:
    api = await api_factory(app_env="development", cookie_secure=False)
    response = await register(api)
    header = response.headers["set-cookie"].lower()
    assert "secure" not in header
    assert "httponly" in header
