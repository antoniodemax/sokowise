"""`app.mpesa.parser`: pure parsing of Safaricom confirmation SMS.

Samples use synthetic names, masked numbers and codes `RK1TEST0xx`. The Till and
Paybill merchant wordings are the best current knowledge; the pilot's real messages
are the authority and may add cases here.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.models.enums import SmsKind
from app.mpesa.parser import ParsedSms, SmsDirection, parse_mpesa_sms

SEND_MONEY = (
    "RK1TEST001 Confirmed.You have received Ksh1,000.00 from JANE TESTER 0712***456 "
    "on 18/9/26 at 2:15 PM New M-PESA balance is Ksh5,000.00. Separate business and "
    "personal funds through Pochi la Biashara on *334#."
)
POCHI = (
    "RK1TEST002 Confirmed. You have received Ksh500.00 from JOHN TESTER 0722***789 on "
    "18/9/26 at 3:02 PM. New business balance is Ksh12,000.00."
)
TILL = (
    "RK1TEST003 Confirmed. Ksh1,200.00 paid by JOHN TESTER 0722***789 on 18/9/26 at "
    "3:10 PM. New Till balance is Ksh20,000.00."
)
PAYBILL = (
    "RK1TEST004 Confirmed. Ksh2,000.00 received from JOHN TESTER 0722***789 for account "
    "SHOP12 on 18/9/26 at 4:00 PM. New Utility balance is Ksh30,000.00."
)
SENT = (
    "RK1TEST005 Confirmed. Ksh1,000.00 sent to JANE TESTER 0712***456 on 18/9/26 at 2:15 PM. "
    "New M-PESA balance is Ksh4,000.00. Transaction cost, Ksh0.00."
)
PAID_TO = (
    "RK1TEST006 Confirmed. Ksh1,200.00 paid to DUKA TESTER. on 18/9/26 at 3:10 PM.New M-PESA "
    "balance is Ksh3,000.00. Transaction cost, Ksh0.00."
)
PAID_PAYBILL = (
    "RK1TEST007 Confirmed. Ksh2,000.00 sent to KPLC TESTER for account 123456 on 18/9/26 "
    "at 4:00 PM New M-PESA balance is Ksh1,000.00."
)


def _at(hour: int, minute: int) -> datetime:
    """18 Sept 2026 local Nairobi time as UTC (Nairobi is UTC+3, no DST)."""
    return datetime(2026, 9, 18, hour - 3, minute, tzinfo=UTC)


def test_send_money_received() -> None:
    parsed = parse_mpesa_sms(SEND_MONEY)
    assert parsed == ParsedSms(
        code="RK1TEST001",
        amount=Decimal("1000.00"),
        direction=SmsDirection.RECEIVED,
        kind=SmsKind.SEND_MONEY,
        sender_name="JANE TESTER",
        sender_phone_masked="0712***456",
        sender_last3="456",
        account_reference=None,
        occurred_at=_at(14, 15),
        raw_text=SEND_MONEY,
    )
    assert isinstance(parsed.amount, Decimal)


def test_pochi_received() -> None:
    parsed = parse_mpesa_sms(POCHI)
    assert parsed is not None
    assert (parsed.code, parsed.amount, parsed.kind, parsed.direction) == (
        "RK1TEST002",
        Decimal("500.00"),
        SmsKind.POCHI,
        SmsDirection.RECEIVED,
    )
    assert parsed.sender_name == "JOHN TESTER" and parsed.sender_last3 == "789"
    assert parsed.occurred_at == _at(15, 2)


def test_till_paid_by() -> None:
    parsed = parse_mpesa_sms(TILL)
    assert parsed is not None
    assert parsed.kind is SmsKind.TILL and parsed.direction is SmsDirection.RECEIVED
    assert parsed.amount == Decimal("1200.00") and parsed.sender_name == "JOHN TESTER"


def test_paybill_received_with_account() -> None:
    parsed = parse_mpesa_sms(PAYBILL)
    assert parsed is not None
    assert parsed.kind is SmsKind.PAYBILL and parsed.account_reference == "SHOP12"
    assert parsed.direction is SmsDirection.RECEIVED and parsed.amount == Decimal("2000.00")


@pytest.mark.parametrize("text", [SENT, PAID_TO, PAID_PAYBILL])
def test_customer_side_messages_are_sent(text: str) -> None:
    parsed = parse_mpesa_sms(text)
    assert parsed is not None
    assert parsed.direction is SmsDirection.SENT
    # The transaction amount, not the balance or the fee.
    assert parsed.amount in {Decimal("1000.00"), Decimal("1200.00"), Decimal("2000.00")}


def test_tolerates_case_currency_and_line_breaks() -> None:
    text = (
        "rk1test008 Confirmed.\nYou have received KES 1,000.00\nfrom JANE TESTER 0712***456\n"
        "on 18/09/2026 at 2:15 pm\nNew M-PESA balance is KES 5,000.00."
    )
    parsed = parse_mpesa_sms(text)
    assert parsed is not None
    assert parsed.code == "RK1TEST008" and parsed.amount == Decimal("1000.00")
    assert parsed.occurred_at == _at(14, 15) and parsed.raw_text == text


def test_amount_without_decimals_and_full_phone() -> None:
    text = (
        "RK1TEST011 Confirmed. You have received Ksh750 from AMINA TESTER 0733123456 on "
        "1/1/26 at 12:05 AM. New business balance is Ksh900."
    )
    parsed = parse_mpesa_sms(text)
    assert parsed is not None
    assert parsed.amount == Decimal("750.00")
    assert parsed.sender_phone_masked == "0733123456" and parsed.sender_last3 == "456"
    assert parsed.occurred_at == datetime(2025, 12, 31, 21, 5, tzinfo=UTC)  # 00:05 local


def test_missing_phone_gives_name_only() -> None:
    text = (
        "RK1TEST009 Confirmed. You have received Ksh750.00 from JANE TESTER on 18/9/26 at "
        "9:05 AM. New M-PESA balance is Ksh2,000.00."
    )
    parsed = parse_mpesa_sms(text)
    assert parsed is not None
    assert parsed.sender_name == "JANE TESTER"
    assert parsed.sender_phone_masked is None and parsed.sender_last3 is None
    assert parsed.occurred_at == _at(9, 5)


def test_noon_and_midnight() -> None:
    noon = (
        "RK1TEST012 Confirmed. You have received Ksh10.00 from A B 0700***000 on 18/9/26 at "
        "12:00 PM. New business balance is Ksh1.00."
    )
    parsed = parse_mpesa_sms(noon)
    assert parsed is not None and parsed.occurred_at == _at(12, 0)


@pytest.mark.parametrize(
    "text",
    [
        "Hello, please send stock tomorrow",
        "Confirmed. Ksh100.00 received from X 0712***456 on 18/9/26 at 1:00 PM",  # no code
        "RK1TEST010 Confirmed. You have received Ksh5.00 from X 0712***456",  # no date
        "RK1TEST010 Confirmed. You have received nothing on 18/9/26 at 1:00 PM",  # no amount
        "RK1TEST013 Confirmed. You have received Ksh0.00 from X on 18/9/26 at 1:00 PM",  # zero
        "RK1TEST014 Confirmed. You have received Ksh10.00 from X on 31/2/26 at 1:00 PM",  # bad date
        "",
    ],
)
def test_unparseable_returns_none(text: str) -> None:
    assert parse_mpesa_sms(text) is None


def test_parser_is_pure() -> None:
    assert parse_mpesa_sms(POCHI) == parse_mpesa_sms(POCHI)
