"""Money arithmetic (PRD BR-9, BR-14): exact decimals, largest-remainder allocation."""

from decimal import Decimal

import pytest
from app.services.money import allocate_discount, line_total, round_money

D = Decimal


def test_line_total_rounds_half_up_at_the_line() -> None:
    assert line_total(D("3"), D("0.10")) == D("0.30")  # the classic float trap
    assert line_total(D("0.5"), D("33.33")) == D("16.67")  # 16.665 → half-up
    assert line_total(D("1.5"), D("0.01")) == D("0.02")  # 0.015 → half-up
    assert line_total(D("2.250"), D("1.00")) == D("2.25")
    assert round_money(D("2.345")) == D("2.35")
    assert round_money(D("2.344")) == D("2.34")


@pytest.mark.parametrize(
    ("discount", "totals", "expected"),
    [
        ("0", ["10.00", "20.00"], ["0.00", "0.00"]),
        ("3.00", ["10.00", "20.00"], ["1.00", "2.00"]),
        # 100 across three equal lines: 33.33 + 33.33 + 33.34 (largest remainder → last? no:
        # all remainders equal, earlier lines win the extra cent).
        ("100.00", ["50.00", "50.00", "50.00"], ["33.34", "33.33", "33.33"]),
        ("1.00", ["1.00", "1.00", "1.00"], ["0.34", "0.33", "0.33"]),
        # 0.01 can only go to one line: the one with the largest share.
        ("0.01", ["10.00", "90.00"], ["0.00", "0.01"]),
        # Uneven lines producing fractional cents.
        ("10.00", ["12.34", "56.78", "9.10"], ["1.58", "7.26", "1.16"]),
        ("0.05", ["0.01", "0.02", "0.03"], ["0.01", "0.02", "0.02"]),
        # Whole subtotal discounted: every line fully discounted, nothing above line total.
        ("60.00", ["10.00", "20.00", "30.00"], ["10.00", "20.00", "30.00"]),
        ("7.00", ["7.00"], ["7.00"]),
        ("0.00", ["0.00"], ["0.00"]),
    ],
)
def test_allocation_sums_exactly_and_never_exceeds_a_line(
    discount: str, totals: list[str], expected: list[str]
) -> None:
    result = allocate_discount(D(discount), [D(t) for t in totals])
    assert result == [D(e) for e in expected]
    assert sum(result, D("0")) == D(discount)
    assert all(alloc <= D(t) for alloc, t in zip(result, totals, strict=True))
    assert all(alloc >= 0 for alloc in result)


def test_allocation_over_many_awkward_lines_has_no_drift() -> None:
    totals = [D(f"{n}.{n % 100:02d}") for n in range(1, 41)]  # 1.01, 2.02, … 40.40
    for discount in (D("0.01"), D("0.99"), D("13.37"), D("100.00"), D("777.77")):
        result = allocate_discount(discount, totals)
        assert sum(result, D("0")) == discount
        assert all(0 <= a <= t for a, t in zip(result, totals, strict=True))


def test_allocation_rejects_a_discount_above_the_subtotal() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        allocate_discount(D("10.01"), [D("10.00")])
    assert allocate_discount(D("1"), []) == []
