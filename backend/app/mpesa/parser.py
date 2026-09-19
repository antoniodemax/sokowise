"""Parse a Safaricom M-Pesa confirmation SMS into its fields.

The shop's phone receives one SMS per payment (Pochi la Biashara, Buy Goods / Till,
Paybill, or a plain "send money"). The wording differs by product and has changed over
the years, so the parser is deliberately tolerant: it needs a transaction code, an
amount and a date; everything else is best effort. Anything it cannot read returns
None and is kept by the caller as raw text so unknown formats surface during the pilot.

Money is `Decimal`, never float. Times are parsed as Africa/Nairobi (M-Pesa prints
local time) and returned aware in UTC.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.models.enums import SmsKind

NAIROBI = ZoneInfo("Africa/Nairobi")
CENT = Decimal("0.01")
MAX_NAME_LENGTH = 120


class SmsDirection(StrEnum):
    RECEIVED = "RECEIVED"  # money came into the shop's line
    SENT = "SENT"  # the customer-side copy, or an outgoing payment: not shop income
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ParsedSms:
    code: str
    amount: Decimal
    direction: SmsDirection
    kind: SmsKind
    sender_name: str | None
    sender_phone_masked: str | None
    sender_last3: str | None
    account_reference: str | None
    occurred_at: datetime
    raw_text: str


# First token of every confirmation is the 10-character transaction code.
_CODE = re.compile(r"^\s*([A-Z0-9]{10})\s+Confirmed\b", re.IGNORECASE)
# The first money figure is the transaction amount; balances and fees come later.
_AMOUNT = re.compile(r"\b(?:Ksh|KES)\.?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?", re.IGNORECASE)
_RECEIVED = re.compile(r"\b(?:you have received|received from|paid by)\b", re.IGNORECASE)
_SENT = re.compile(
    r"\b(?:sent to|paid to|withdrawn?|withdraw|bought|of airtime|airtime for|give)\b",
    re.IGNORECASE,
)
_PHONE = r"(?:0[17]\d{2}\*{2,3}\d{3}|\+?254\d{9}|0[17]\d{8})"
_FROM = re.compile(rf"\bfrom\s+(?P<name>.+?)\s+(?P<phone>{_PHONE})", re.IGNORECASE)
_FROM_NO_PHONE = re.compile(r"\bfrom\s+(?P<name>.+?)\s+(?:on\s+\d|for account\b)", re.IGNORECASE)
_PAID_BY = re.compile(rf"\bpaid by\s+(?P<name>.+?)\s+(?P<phone>{_PHONE})", re.IGNORECASE)
_ACCOUNT = re.compile(
    r"\b(?:for account|Account Number)\s+(?P<acct>[A-Z0-9][A-Z0-9\-/_.]{0,63})", re.IGNORECASE
)
_WHEN = re.compile(
    r"\bon\s+(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\s+at\s+(\d{1,2}):(\d{2})\s*(AM|PM)\b", re.IGNORECASE
)
_TRAILING_PUNCT = ".,;:"
# The shop's own balance is private and not needed for matching: it is dropped before the
# message is stored. Matches "New M-PESA balance is Ksh…", "New business balance…",
# "New Till balance…", "New Utility balance…" up to the end of that sentence.
_BALANCE = re.compile(
    r"\s*New\s+[A-Za-z\- ]*balance\s+is\s+(?:Ksh|KES)\.?\s?[\d,]+(?:\.\d{1,2})?\.?",
    re.IGNORECASE,
)


def redact_balance(text: str) -> str:
    """Return `text` without the "New … balance is Ksh…" sentence (DATA_MAPPING §3.19)."""
    return _BALANCE.sub("", text).strip()


def parse_mpesa_sms(text: str) -> ParsedSms | None:
    """Return the parsed message, or None when code, amount or date cannot be found."""
    raw = text
    flat = " ".join(text.split())
    code_match = _CODE.match(flat)
    amount_match = _AMOUNT.search(flat)
    when_match = _WHEN.search(flat)
    if code_match is None or amount_match is None or when_match is None:
        return None
    amount = _amount(amount_match.group(1), amount_match.group(2))
    occurred_at = _occurred_at(when_match)
    if amount is None or occurred_at is None:
        return None

    received = _RECEIVED.search(flat) is not None
    sent = _SENT.search(flat) is not None
    if received:
        direction = SmsDirection.RECEIVED
    elif sent:
        direction = SmsDirection.SENT
    else:
        direction = SmsDirection.UNKNOWN

    name: str | None = None
    phone: str | None = None
    for pattern in (_FROM, _PAID_BY):
        found = pattern.search(flat)
        if found:
            name, phone = found.group("name"), found.group("phone")
            break
    if name is None:
        found = _FROM_NO_PHONE.search(flat)
        if found:
            name = found.group("name")
    account = _ACCOUNT.search(flat)

    return ParsedSms(
        code=code_match.group(1).upper(),
        amount=amount,
        direction=direction,
        kind=_kind(flat, direction, account is not None),
        sender_name=_clean_name(name),
        sender_phone_masked=phone,
        sender_last3=phone[-3:] if phone and phone[-3:].isdigit() else None,
        account_reference=account.group("acct").rstrip(_TRAILING_PUNCT) if account else None,
        occurred_at=occurred_at,
        raw_text=raw,
    )


def _amount(whole: str, cents: str | None) -> Decimal | None:
    try:
        value = Decimal(whole.replace(",", ""))
        if cents:
            value += Decimal(cents.ljust(2, "0")) / 100
        value = value.quantize(CENT)
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _occurred_at(match: re.Match[str]) -> datetime | None:
    day, month, year, hour, minute, meridian = match.groups()
    try:
        y = int(year)
        y = 2000 + y if y < 100 else y
        h = int(hour) % 12 + (12 if meridian.upper() == "PM" else 0)
        local = datetime(y, int(month), int(day), h, int(minute), tzinfo=NAIROBI)
    except ValueError:
        return None
    return local.astimezone(UTC)


def _kind(flat: str, direction: SmsDirection, has_account: bool) -> SmsKind:
    lowered = flat.lower()
    if "new business balance" in lowered:
        return SmsKind.POCHI
    if has_account:
        return SmsKind.PAYBILL
    if "new till balance" in lowered or "new utility balance" in lowered or "paid by" in lowered:
        return SmsKind.TILL
    if "paid to" in lowered:
        return SmsKind.TILL
    if "new m-pesa balance" in lowered and direction is not SmsDirection.UNKNOWN:
        return SmsKind.SEND_MONEY
    return SmsKind.UNKNOWN


def _clean_name(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = " ".join(name.split()).strip(_TRAILING_PUNCT + " ")
    return cleaned[:MAX_NAME_LENGTH] or None


__all__ = ["ParsedSms", "SmsDirection", "parse_mpesa_sms", "redact_balance"]
