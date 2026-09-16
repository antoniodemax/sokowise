"""Money arithmetic for sales (PRD BR-9, BR-14). Pure functions, Decimal only."""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def round_money(value: Decimal) -> Decimal:
    """Half-up to 2 dp — the line-level rounding rule (BR-9)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    return round_money(quantity * unit_price)


def allocate_discount(discount: Decimal, line_totals: list[Decimal]) -> list[Decimal]:
    """Split a sale-level discount across lines pro-rata by line total (BR-14).

    Largest-remainder rounding: every line gets the floor of its exact share in cents,
    then the leftover cents go, one each, to the lines with the largest fractional
    remainders (earlier lines win ties). The result sums to `discount` exactly and no
    line receives more than its own total.
    """
    if not line_totals:
        return []
    discount = discount.quantize(CENT)
    subtotal = sum(line_totals, Decimal("0"))
    if discount == 0 or subtotal == 0:
        return [Decimal("0.00") for _ in line_totals]
    if discount > subtotal:
        msg = "discount exceeds subtotal"
        raise ValueError(msg)
    exact = [discount * total / subtotal for total in line_totals]
    floors = [share.quantize(CENT, rounding=ROUND_DOWN) for share in exact]
    leftover_cents = int((discount - sum(floors, Decimal("0"))) / CENT)
    by_remainder = sorted(range(len(line_totals)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in by_remainder[:leftover_cents]:
        floors[i] += CENT
    return floors
