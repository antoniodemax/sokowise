"""Sign in with Google (ARCHITECTURE §5.1): verified identity → session or finish-up form."""

import uuid
from http import HTTPStatus
from typing import Any

import pytest
from app.api.v1.auth import get_google_verifier
from app.auth.google import GoogleIdentity, GoogleTokenError, identity_from_claims
from app.models import User
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db.auth_helpers import (
    PASSWORD,
    bearer,
    error_code,
    login,
    refresh,
    refresh_cookie,
    register,
    unique_phone,
)
from tests.db.conftest import ApiFactory

pytestmark = [pytest.mark.db, pytest.mark.anyio]

GOOGLE_URL = "/api/v1/auth/google"
GOOGLE_REGISTER_URL = "/api/v1/auth/google/register"
GOOD: dict[str, Any] = {
    "iss": "https://accounts.google.com",
    "sub": "1",
    "email": "a@x.com",
    "email_verified": True,
}


class FakeVerifier:
    """Maps credential strings to identities; anything else is an invalid token."""

    def __init__(self, identities: dict[str, GoogleIdentity]) -> None:
        self.identities = identities
        self.calls: list[str] = []

    def verify(self, credential: str) -> GoogleIdentity:
        self.calls.append(credential)
        try:
            return self.identities[credential]
        except KeyError:
            raise GoogleTokenError from None


async def make_google_api(api_factory: ApiFactory, verifier: FakeVerifier) -> AsyncClient:
    api = await api_factory(google_client_id="test-client-id.apps.googleusercontent.com")
    transport = api._transport
    assert isinstance(transport, ASGITransport)
    transport.app.dependency_overrides[get_google_verifier] = lambda: verifier  # type: ignore[attr-defined]
    return api


def amina(email: str = "amina@example.com") -> GoogleIdentity:
    return GoogleIdentity(sub="google-sub-amina", email=email, name="Amina Wanjiru")


async def test_new_google_user_finishes_up_then_signs_in_without_a_password(
    api_factory: ApiFactory, db_session: AsyncSession
) -> None:
    verifier = FakeVerifier({"cred-amina-0123456789abcdef": amina()})
    api = await make_google_api(api_factory, verifier)

    first = await api.post(GOOGLE_URL, json={"credential": "cred-amina-0123456789abcdef"})
    assert first.status_code == HTTPStatus.OK, first.text
    pending = first.json()
    assert pending["status"] == "needs_registration"
    assert pending["email"] == "amina@example.com" and pending["name"] == "Amina Wanjiru"
    assert refresh_cookie(api) is None  # no session yet

    phone = unique_phone()
    done = await api.post(
        GOOGLE_REGISTER_URL,
        json={
            "registration_token": pending["registration_token"],
            "phone": phone,
            "business_name": "Amina Duka",
            "business_type": "BOUTIQUE",
        },
    )
    assert done.status_code == HTTPStatus.CREATED, done.text
    body = done.json()
    assert body["user"]["email"] == "amina@example.com"
    assert body["user"]["full_name"] == "Amina Wanjiru"
    assert body["business"]["name"] == "Amina Duka" and body["role"] == "OWNER"
    assert refresh_cookie(api) is not None
    user = await db_session.get(User, uuid.UUID(body["user"]["id"]))
    assert user is not None
    assert user.password_hash is None and user.google_sub == "google-sub-amina"
    assert user.phone == phone

    # Password login never works for a Google-only account, and says nothing special.
    denied = await login(api, phone, PASSWORD)
    assert denied.status_code == HTTPStatus.UNAUTHORIZED
    assert error_code(denied) == "INVALID_CREDENTIALS"

    # The next Google sign-in opens a session straight away.
    api.cookies.clear()
    again = await api.post(GOOGLE_URL, json={"credential": "cred-amina-0123456789abcdef"})
    assert again.status_code == HTTPStatus.OK
    assert "access_token" in again.json() and again.json()["user"]["id"] == body["user"]["id"]
    assert refresh_cookie(api) is not None
    me = await api.get("/api/v1/auth/me", headers=bearer(again.json()["access_token"]))
    assert me.status_code == HTTPStatus.OK
    await db_session.refresh(user)
    assert user.last_login_at is not None


async def test_existing_account_with_the_same_verified_email_is_linked(
    api_factory: ApiFactory, db_session: AsyncSession
) -> None:
    verifier = FakeVerifier({"cred-amina-0123456789abcdef": amina("Amina@Example.com")})
    api = await make_google_api(api_factory, verifier)
    registered = await register(api, email="amina@example.com", business_name="Amina Duka")
    assert registered.status_code == HTTPStatus.CREATED
    api.cookies.clear()

    response = await api.post(GOOGLE_URL, json={"credential": "cred-amina-0123456789abcdef"})
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["user"]["id"] == registered.json()["user"]["id"]
    user = await db_session.get(User, uuid.UUID(registered.json()["user"]["id"]))
    assert user is not None and user.google_sub == "google-sub-amina"
    assert user.password_hash is not None  # the password still works too
    assert (await login(api, registered.json()["user"]["phone"])).status_code == HTTPStatus.OK


async def test_bad_credentials_forged_tokens_and_duplicates(
    api_factory: ApiFactory,
) -> None:
    verifier = FakeVerifier({"cred-amina-0123456789abcdef": amina()})
    api = await make_google_api(api_factory, verifier)

    bad = await api.post(GOOGLE_URL, json={"credential": "not-a-google-token-at-all"})
    assert bad.status_code == HTTPStatus.UNAUTHORIZED
    assert error_code(bad) == "GOOGLE_TOKEN_INVALID"

    forged = await api.post(
        GOOGLE_REGISTER_URL,
        json={
            "registration_token": "forged.token.value-that-is-long-enough",
            "phone": unique_phone(),
            "business_name": "Evil Duka",
        },
    )
    assert forged.status_code == HTTPStatus.UNAUTHORIZED
    assert error_code(forged) == "SIGNUP_TOKEN_INVALID"

    # A phone that already belongs to someone cannot be claimed through Google.
    taken = await register(api)
    assert taken.status_code == HTTPStatus.CREATED
    api.cookies.clear()
    pending = (
        await api.post(GOOGLE_URL, json={"credential": "cred-amina-0123456789abcdef"})
    ).json()
    dup = await api.post(
        GOOGLE_REGISTER_URL,
        json={
            "registration_token": pending["registration_token"],
            "phone": taken.json()["user"]["phone"],
            "business_name": "Amina Duka",
        },
    )
    assert dup.status_code == HTTPStatus.CONFLICT
    assert error_code(dup) == "ACCOUNT_EXISTS"


async def test_google_is_503_until_a_client_id_is_configured(api: AsyncClient) -> None:
    response = await api.post(GOOGLE_URL, json={"credential": "cred-amina-0123456789abcdef"})
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert error_code(response) == "GOOGLE_NOT_CONFIGURED"
    response = await api.post(
        GOOGLE_REGISTER_URL,
        json={"registration_token": "x" * 40, "phone": unique_phone(), "business_name": "D"},
    )
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE


@pytest.mark.parametrize(
    ("claims", "ok"),
    [
        (
            {
                "iss": "https://accounts.google.com",
                "sub": "1",
                "email": "A@x.com",
                "email_verified": True,
            },
            True,
        ),
        (
            {"iss": "accounts.google.com", "sub": "1", "email": "a@x.com", "email_verified": True},
            True,
        ),
        (
            {"iss": "https://evil.example", "sub": "1", "email": "a@x.com", "email_verified": True},
            False,
        ),
        (
            {
                "iss": "https://accounts.google.com",
                "sub": "1",
                "email": "a@x.com",
                "email_verified": False,
            },
            False,
        ),
        ({"iss": "https://accounts.google.com", "sub": "1", "email": "a@x.com"}, False),
        (
            {
                "iss": "https://accounts.google.com",
                "sub": "",
                "email": "a@x.com",
                "email_verified": True,
            },
            False,
        ),
    ],
)
def test_identity_claims_must_come_from_google_with_a_verified_email(
    claims: dict[str, Any], ok: bool
) -> None:
    if ok:
        identity = identity_from_claims(claims)
        assert identity.email == "a@x.com" and identity.sub == "1"
    else:
        with pytest.raises(GoogleTokenError):
            identity_from_claims(claims)


async def test_refresh_after_google_sign_in_rotates_like_any_session(
    api_factory: ApiFactory,
) -> None:
    verifier = FakeVerifier({"cred-amina-0123456789abcdef": amina()})
    api = await make_google_api(api_factory, verifier)
    pending = (
        await api.post(GOOGLE_URL, json={"credential": "cred-amina-0123456789abcdef"})
    ).json()
    done = await api.post(
        GOOGLE_REGISTER_URL,
        json={
            "registration_token": pending["registration_token"],
            "phone": unique_phone(),
            "business_name": "Amina Duka",
        },
    )
    assert done.status_code == HTTPStatus.CREATED
    rotated = await refresh(api)
    assert rotated.status_code == HTTPStatus.OK and rotated.json()["access_token"]
