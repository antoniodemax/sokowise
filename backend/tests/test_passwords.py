"""Argon2id hashing (docs/ARCHITECTURE.md §5.2)."""

import pytest
from app.core.passwords import (
    ARGON2_MEMORY_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    DUMMY_PASSWORD_HASH,
    MAX_PASSWORD_LENGTH,
    hash_password,
    needs_rehash,
    verify_password,
)
from argon2 import PasswordHasher


def test_hash_is_argon2id_with_the_documented_parameters() -> None:
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("$argon2id$v=19$")
    assert f"m={ARGON2_MEMORY_KIB},t={ARGON2_TIME_COST},p={ARGON2_PARALLELISM}" in encoded
    assert (ARGON2_MEMORY_KIB, ARGON2_TIME_COST, ARGON2_PARALLELISM) == (19 * 1024, 2, 1)


def test_correct_password_verifies() -> None:
    encoded = hash_password("correct horse battery staple")
    assert verify_password(encoded, "correct horse battery staple") is True


def test_wrong_password_does_not_verify() -> None:
    encoded = hash_password("correct horse battery staple")
    assert verify_password(encoded, "correct horse battery stapl") is False
    assert verify_password(encoded, "Correct horse battery staple") is False


def test_same_password_hashes_differently_each_time() -> None:
    password = "correct horse battery staple"  # noqa: S105
    first, second = hash_password(password), hash_password(password)
    assert first != second  # random salt
    assert verify_password(first, password) and verify_password(second, password)


def test_plaintext_is_not_recoverable_from_the_hash() -> None:
    assert "battery" not in hash_password("correct horse battery staple")


@pytest.mark.parametrize("bad", ["", "x" * (MAX_PASSWORD_LENGTH + 1)])
def test_hashing_rejects_empty_and_oversized_passwords(bad: str) -> None:
    with pytest.raises(ValueError, match="password"):
        hash_password(bad)


def test_verify_never_raises_for_bad_input() -> None:
    encoded = hash_password("correct horse battery staple")
    assert verify_password(encoded, "") is False
    assert verify_password(encoded, "x" * (MAX_PASSWORD_LENGTH + 1)) is False
    assert verify_password("not-a-real-hash", "anything") is False
    assert verify_password("", "anything") is False


def test_needs_rehash_when_parameters_change() -> None:
    current = hash_password("correct horse battery staple")
    assert needs_rehash(current) is False
    weaker = PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1).hash("pw")
    assert needs_rehash(weaker) is True
    assert needs_rehash("garbage") is True


def test_dummy_hash_is_a_real_hash_that_matches_nothing_obvious() -> None:
    assert DUMMY_PASSWORD_HASH.startswith("$argon2id$")
    assert verify_password(DUMMY_PASSWORD_HASH, "password") is False
