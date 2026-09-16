"""JWT access tokens and opaque refresh tokens (docs/ARCHITECTURE.md §5.1)."""

import base64
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.core.config import Settings
from app.core.tokens import (
    ACCESS_TOKEN_TYPE,
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_refresh_token,
)

USER_ID = uuid.uuid4()
BUSINESS_ID = uuid.uuid4()


@pytest.fixture
def settings() -> Settings:
    return Settings()


def _payload(token: str) -> dict[str, object]:
    body = token.split(".")[1]
    padded = body + "=" * (-len(body) % 4)
    decoded: dict[str, object] = json.loads(base64.urlsafe_b64decode(padded))
    return decoded


def _reencode(settings: Settings, payload: dict[str, object]) -> str:
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def _claims(settings: Settings, token: str) -> dict[str, object]:
    claims: dict[str, object] = jwt.decode(
        token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"]
    )
    return claims


def test_access_token_round_trips_and_carries_only_the_documented_claims(
    settings: Settings,
) -> None:
    token, expires_at = create_access_token(settings, user_id=USER_ID, business_id=BUSINESS_ID)
    claims = decode_access_token(settings, token)
    assert (claims.user_id, claims.business_id) == (USER_ID, BUSINESS_ID)
    assert claims.expires_at == expires_at.replace(microsecond=0)
    assert claims.expires_at - claims.issued_at == timedelta(
        minutes=settings.access_token_ttl_minutes
    )
    payload = _payload(token)
    assert set(payload) == {"sub", "bid", "jti", "iat", "exp", "typ"}
    assert payload["typ"] == ACCESS_TOKEN_TYPE
    assert "role" not in payload


def test_each_token_has_a_unique_jti(settings: Settings) -> None:
    first, _ = create_access_token(settings, user_id=USER_ID, business_id=BUSINESS_ID)
    second, _ = create_access_token(settings, user_id=USER_ID, business_id=BUSINESS_ID)
    assert _payload(first)["jti"] != _payload(second)["jti"]


def test_expired_token_is_rejected(settings: Settings) -> None:
    long_ago = datetime.now(UTC) - timedelta(hours=2)
    token, _ = create_access_token(settings, user_id=USER_ID, business_id=BUSINESS_ID, now=long_ago)
    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, token)


def test_token_signed_with_another_secret_is_rejected(settings: Settings) -> None:
    other = Settings(jwt_secret="a-completely-different-secret-of-32-chars!!")  # noqa: S106
    token, _ = create_access_token(other, user_id=USER_ID, business_id=BUSINESS_ID)
    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, token)


def test_tampered_payload_is_rejected(settings: Settings) -> None:
    token, _ = create_access_token(settings, user_id=USER_ID, business_id=BUSINESS_ID)
    header, _, signature = token.split(".")
    payload = _payload(token)
    payload["bid"] = str(uuid.uuid4())
    forged_body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, f"{header}.{forged_body}.{signature}")


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer x", chr(0)])
def test_malformed_tokens_are_rejected(settings: Settings, garbage: str) -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, garbage)


def test_alg_none_is_rejected(settings: Settings) -> None:
    token = jwt.encode(
        {"sub": str(USER_ID), "bid": str(BUSINESS_ID), "jti": "x", "iat": 1, "exp": 2**31},
        key="",
        algorithm="none",
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, token)


def test_wrong_token_type_is_rejected(settings: Settings) -> None:
    token, _ = create_access_token(settings, user_id=USER_ID, business_id=BUSINESS_ID)
    payload = _claims(settings, token)
    payload["typ"] = "refresh"
    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, _reencode(settings, payload))


@pytest.mark.parametrize("missing", ["sub", "bid", "jti", "iat", "exp", "typ"])
def test_missing_required_claim_is_rejected(settings: Settings, missing: str) -> None:
    token, _ = create_access_token(settings, user_id=USER_ID, business_id=BUSINESS_ID)
    payload = _claims(settings, token)
    del payload[missing]
    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, _reencode(settings, payload))


def test_non_uuid_subject_is_rejected(settings: Settings) -> None:
    token, _ = create_access_token(settings, user_id=USER_ID, business_id=BUSINESS_ID)
    payload = _claims(settings, token)
    payload["sub"] = "admin"
    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, _reencode(settings, payload))


def test_issuer_and_audience_are_enforced_when_configured() -> None:
    strict = Settings(jwt_issuer="sokowise", jwt_audience="sokowise-api")
    token, _ = create_access_token(strict, user_id=USER_ID, business_id=BUSINESS_ID)
    payload = _payload(token)
    assert (payload["iss"], payload["aud"]) == ("sokowise", "sokowise-api")
    decode_access_token(strict, token)
    # A token minted without those claims does not pass a verifier that requires them.
    plain, _ = create_access_token(Settings(), user_id=USER_ID, business_id=BUSINESS_ID)
    with pytest.raises(InvalidTokenError):
        decode_access_token(strict, plain)
    # And a different audience is rejected.
    other = Settings(jwt_issuer="sokowise", jwt_audience="someone-else")
    with pytest.raises(InvalidTokenError):
        decode_access_token(other, token)


def _is_not_a_uuid(token: str) -> bool:
    try:
        uuid.UUID(token)
    except ValueError:
        return True
    return False


def test_refresh_tokens_are_random_and_long() -> None:
    tokens = {generate_refresh_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(len(token) >= 43 for token in tokens)  # 32 bytes, url-safe base64
    assert all(_is_not_a_uuid(token) for token in tokens)


def test_refresh_token_hash_is_sha256_hex() -> None:
    token = generate_refresh_token()
    assert hash_refresh_token(token) == hashlib.sha256(token.encode()).hexdigest()
    assert len(hash_refresh_token(token)) == 64
    assert hash_refresh_token(token) != hash_refresh_token(token + "x")
