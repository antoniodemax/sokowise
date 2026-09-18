"""Verification of Google ID tokens for "Sign in with Google" (docs/ARCHITECTURE.md §5.1).

The browser obtains an ID token from Google Identity Services and posts it to us. We verify
the RS256 signature against Google's published keys, the audience (our client id), the
issuer and expiry, and require a verified email. Nothing about the Google account is
trusted before that check. The verifier is a small protocol so tests inject a fake.
"""

from dataclasses import dataclass
from typing import Protocol

import jwt
from jwt import PyJWKClient

from app.core.config import Settings

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})


class GoogleTokenError(Exception):
    """The credential is not a valid, verified Google ID token for this client id."""


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None


class GoogleVerifier(Protocol):
    def verify(self, credential: str) -> GoogleIdentity: ...


class JwksGoogleVerifier:
    def __init__(self, client_id: str, *, jwks_url: str = GOOGLE_JWKS_URL) -> None:
        self._client_id = client_id
        self._jwks = PyJWKClient(jwks_url, cache_keys=True)

    def verify(self, credential: str) -> GoogleIdentity:
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(credential)
            payload = jwt.decode(
                credential,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._client_id,
                options={"require": ["sub", "email", "exp", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise GoogleTokenError from exc
        return identity_from_claims(payload)


def identity_from_claims(payload: dict[str, object]) -> GoogleIdentity:
    """Shared by the real verifier and tests: the checks after signature and audience."""
    if payload.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleTokenError
    if payload.get("email_verified") is not True:
        raise GoogleTokenError
    email = str(payload.get("email") or "").strip().lower()
    sub = str(payload.get("sub") or "")
    if not email or not sub:
        raise GoogleTokenError
    name = payload.get("name")
    return GoogleIdentity(sub=sub, email=email, name=str(name) if name else None)


def build_google_verifier(settings: Settings) -> GoogleVerifier | None:
    """None → the Google endpoints answer 503 GOOGLE_NOT_CONFIGURED."""
    if not settings.google_client_id:
        return None
    return JwksGoogleVerifier(settings.google_client_id)


__all__ = [
    "GoogleIdentity",
    "GoogleTokenError",
    "GoogleVerifier",
    "JwksGoogleVerifier",
    "build_google_verifier",
    "identity_from_claims",
]
