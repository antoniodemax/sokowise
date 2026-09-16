"""No password or token material may reach the logs (ROADMAP Phase 3 completion criteria)."""

import logging
from http import HTTPStatus

import pytest
from app.core.logging import JsonFormatter
from httpx import AsyncClient

from tests.db.auth_helpers import (
    CHANGE_PASSWORD_URL,
    OTHER_PASSWORD,
    PASSWORD,
    bearer,
    login,
    refresh,
    refresh_cookie,
    register,
    set_refresh_cookie,
)

pytestmark = [pytest.mark.db, pytest.mark.anyio]


async def test_auth_flow_logs_contain_no_secrets(
    api: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    # create_app() re-installed the root handlers; put caplog's back and capture everything.
    logging.getLogger().addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG)

    registered = await register(api, phone="+254700999111")
    assert registered.status_code == HTTPStatus.CREATED
    assert (await login(api, "+254700999111")).status_code == HTTPStatus.OK
    first_refresh = refresh_cookie(api)
    assert (
        await login(api, "+254700999111", "wrong password")
    ).status_code == HTTPStatus.UNAUTHORIZED
    assert (await refresh(api)).status_code == HTTPStatus.OK
    second_refresh = refresh_cookie(api)
    assert first_refresh is not None
    set_refresh_cookie(api, first_refresh)
    assert (await refresh(api)).status_code == HTTPStatus.UNAUTHORIZED  # reuse → warning logged
    changed = await api.post(
        CHANGE_PASSWORD_URL,
        headers=bearer(registered.json()["access_token"]),
        json={"current_password": PASSWORD, "new_password": OTHER_PASSWORD},
    )
    assert changed.status_code == HTTPStatus.OK

    rendered = "\n".join(JsonFormatter().format(record) for record in caplog.records)
    assert "refresh token reuse detected" in rendered  # the interesting event was logged...
    assert "login failed" in rendered
    secrets = [
        PASSWORD,
        OTHER_PASSWORD,
        "wrong password",
        first_refresh,
        second_refresh,
        registered.json()["access_token"],
        changed.json()["access_token"],
        "$argon2",
    ]
    for secret in secrets:
        assert secret and secret not in rendered  # ...but never the material itself
    assert "+254700999111" not in rendered  # nor the identifier (PII), ids only
