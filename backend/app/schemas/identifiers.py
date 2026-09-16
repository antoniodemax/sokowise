"""Normalisation of the login identifiers (docs/DATA_MAPPING.md §3.2).

Phones are stored in E.164 (`+2547…`); emails lower-cased. The same functions run
at registration and at login so a user always finds the account they created.
"""

import re

_E164 = re.compile(r"^\+[1-9]\d{6,14}$")
_KENYA_COUNTRY_CODE = "254"
# Not a full RFC 5322 check; enough to reject junk while accepting real addresses.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_phone(raw: str) -> str:
    """Return the E.164 form of `raw` or raise ValueError.

    Accepts international numbers with a leading `+` and, because the product is
    Kenya-only in MVP (PRD §4), the local forms `07XXXXXXXX` / `01XXXXXXXX` and
    `2547XXXXXXXX`, which become `+254…`.
    """
    digits = re.sub(r"[\s\-().]", "", raw)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    elif digits.startswith("0") and len(digits) == 10:
        digits = f"+{_KENYA_COUNTRY_CODE}{digits[1:]}"
    elif digits.startswith(_KENYA_COUNTRY_CODE) and len(digits) == 12:
        digits = "+" + digits
    if not _E164.fullmatch(digits):
        msg = "phone must be a valid phone number in international format, e.g. +254712345678"
        raise ValueError(msg)
    return digits


def normalize_email(raw: str) -> str:
    """Return the lower-cased, trimmed email or raise ValueError."""
    email = raw.strip().lower()
    if len(email) > 255 or not _EMAIL.fullmatch(email):
        msg = "email must be a valid email address"
        raise ValueError(msg)
    return email


def looks_like_email(identifier: str) -> bool:
    return "@" in identifier
