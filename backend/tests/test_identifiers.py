"""Phone and email normalisation (docs/DATA_MAPPING.md §3.2)."""

import pytest
from app.schemas.identifiers import looks_like_email, normalize_email, normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+254712345678", "+254712345678"),
        ("0712345678", "+254712345678"),
        ("0112345678", "+254112345678"),
        ("254712345678", "+254712345678"),
        ("+254 712 345 678", "+254712345678"),
        ("0712-345-678", "+254712345678"),
        ("00254712345678", "+254712345678"),
        ("+14155552671", "+14155552671"),
    ],
)
def test_phone_normalises_to_e164(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "12345", "abc", "+0712345678", "0712", "+" + "9" * 16])
def test_invalid_phone_is_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="phone"):
        normalize_phone(raw)


def test_email_is_lower_cased_and_trimmed() -> None:
    assert normalize_email("  Amina@Example.COM ") == "amina@example.com"


@pytest.mark.parametrize("raw", ["", "no-at-sign", "a@b", "a b@example.com", "@example.com"])
def test_invalid_email_is_rejected(raw: str) -> None:
    with pytest.raises(ValueError, match="email"):
        normalize_email(raw)


def test_identifier_kind_detection() -> None:
    assert looks_like_email("amina@example.com")
    assert not looks_like_email("0712345678")
