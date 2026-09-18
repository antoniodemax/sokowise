"""Access and refresh token primitives (docs/ARCHITECTURE.md §5.1).

Access tokens are HS256 JWTs. The claims are deliberately minimal: `sub` (user
id), `bid` (the business the session was opened for), `jti`, `iat`, `exp` and
`typ`. There is no role claim; the role is read from the membership row on every
request, and `bid` is only a selector that the membership check must confirm.

Refresh tokens are 256-bit random opaque strings. Only their SHA-256 hash is
stored; the raw value exists in the client's cookie and nowhere else.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import Settings

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"  # noqa: S105 — a claim value, not a secret
SIGNUP_TOKEN_TYPE = "google-signup"  # noqa: S105 — a claim value, not a secret
SIGNUP_TOKEN_TTL = timedelta(minutes=15)
_REQUIRED_CLAIMS = ("sub", "bid", "jti", "iat", "exp", "typ")


class InvalidTokenError(Exception):
    """The token is malformed, tampered with, expired or of the wrong kind.

    Callers map this to a generic 401; the reason is not reported to the client.
    """


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    business_id: uuid.UUID
    token_id: str
    issued_at: datetime
    expires_at: datetime


def create_access_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    business_id: uuid.UUID,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """Return the encoded token and its expiry."""
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.access_token_ttl_minutes)
    payload: dict[str, object] = {
        "sub": str(user_id),
        "bid": str(business_id),
        "jti": uuid.uuid4().hex,
        "iat": issued_at,
        "exp": expires_at,
        "typ": ACCESS_TOKEN_TYPE,
    }
    if settings.jwt_issuer:
        payload["iss"] = settings.jwt_issuer
    if settings.jwt_audience:
        payload["aud"] = settings.jwt_audience
    token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(settings: Settings, token: str) -> AccessTokenClaims:
    """Verify signature, expiry, type and (when configured) issuer/audience."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require": list(_REQUIRED_CLAIMS),
                "verify_aud": settings.jwt_audience is not None,
                "verify_iss": settings.jwt_issuer is not None,
            },
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError from exc
    if payload.get("typ") != ACCESS_TOKEN_TYPE:
        raise InvalidTokenError
    try:
        return AccessTokenClaims(
            user_id=uuid.UUID(str(payload["sub"])),
            business_id=uuid.UUID(str(payload["bid"])),
            token_id=str(payload["jti"]),
            issued_at=datetime.fromtimestamp(int(payload["iat"]), tz=UTC),
            expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise InvalidTokenError from exc


def generate_refresh_token() -> str:
    """256 bits from the OS CSPRNG, URL-safe base64 (43 characters)."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex digest; what `refresh_tokens.token_hash` stores (DATA_MAPPING §3.4)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SignupTokenClaims:
    """A verified Google identity waiting for the finish-up form (ARCHITECTURE §5.1)."""

    google_sub: str
    email: str
    name: str | None


def create_signup_token(settings: Settings, claims: SignupTokenClaims) -> str:
    """Short-lived HS256 token so the finish-up step cannot change the verified email."""
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": claims.google_sub,
        "email": claims.email,
        "name": claims.name,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + SIGNUP_TOKEN_TTL,
        "typ": SIGNUP_TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_signup_token(settings: Settings, token: str) -> SignupTokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "email", "exp", "typ"], "verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError from exc
    if payload.get("typ") != SIGNUP_TOKEN_TYPE:
        raise InvalidTokenError
    name = payload.get("name")
    return SignupTokenClaims(
        google_sub=str(payload["sub"]),
        email=str(payload["email"]),
        name=str(name) if name else None,
    )


def generate_reset_code() -> str:
    """Six digits from the OS CSPRNG (one million possibilities, 5 attempts, 10 minutes)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_reset_code(user_id: uuid.UUID, code: str) -> str:
    """SHA-256 of `user_id:code`; what `password_reset_codes.code_hash` stores."""
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()
