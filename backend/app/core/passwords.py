"""Password hashing with Argon2id (docs/ARCHITECTURE.md §5.2).

Everything Argon2-specific lives here so the parameters (or the algorithm) can
change in one place. The parameters are the OWASP minimum the architecture
starts from; raise `time_cost` first, then `memory_cost`, after measuring on the
deployed instance. Hashes made with older parameters keep verifying and are
replaced on login via `needs_rehash`.

Nothing in this module logs; callers must never log passwords or hashes either.
"""

import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import HashingError, InvalidHashError, VerificationError

ARGON2_TIME_COST = 2
ARGON2_MEMORY_KIB = 19 * 1024  # 19 MiB
ARGON2_PARALLELISM = 1
ARGON2_HASH_LENGTH = 32
ARGON2_SALT_LENGTH = 16

# Bounded so an attacker cannot make the server hash megabytes per login attempt.
MAX_PASSWORD_LENGTH = 128

_hasher = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_KIB,
    parallelism=ARGON2_PARALLELISM,
    hash_len=ARGON2_HASH_LENGTH,
    salt_len=ARGON2_SALT_LENGTH,
    type=Type.ID,
)


def hash_password(password: str) -> str:
    """Return the Argon2id encoded string (`$argon2id$v=19$m=...`) for `password`."""
    if not password:
        msg = "password must not be empty"
        raise ValueError(msg)
    if len(password) > MAX_PASSWORD_LENGTH:
        msg = f"password must be at most {MAX_PASSWORD_LENGTH} characters"
        raise ValueError(msg)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True when `password` matches `password_hash`. Never raises for bad input.

    The comparison inside argon2-cffi is constant-time. An empty or over-long
    password can never match, so it is rejected without hashing.
    """
    if not password or len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError, HashingError):
        # VerifyMismatchError (wrong password) is a VerificationError subclass.
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash was made with parameters other than the current ones."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# Verified against when a login names an unknown account, so the response time does
# not reveal whether the identifier exists (ARCHITECTURE §5.2, account enumeration).
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))
