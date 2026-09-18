"""Starter catalogues: what a shop of each type usually sells, with typical prices.

Built in and curated on purpose: they work offline and without AI billing, are
deterministic, and are easy to correct from pilot feedback. Prices are 2026 Nairobi
retail figures in KSh and are only a starting point the owner edits before saving.
Cost prices are left blank where they vary too much to guess; the owner adds them
later and profit appears then.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import BusinessType, ProductUnit

CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class StarterItem:
    name: str
    selling_price: Decimal
    cost_price: Decimal | None = None
    unit: ProductUnit = ProductUnit.PIECE
    track_inventory: bool = True


def _i(
    name: str,
    price: str,
    cost: str | None = None,
    unit: ProductUnit = ProductUnit.PIECE,
    *,
    tracked: bool = True,
) -> StarterItem:
    return StarterItem(
        name=name,
        selling_price=Decimal(price).quantize(CENT),
        cost_price=Decimal(cost).quantize(CENT) if cost else None,
        unit=unit,
        track_inventory=tracked,
    )


# Every list ends with the untracked "Other" line the quick-sale button relies on.
_OTHER = _i("Other", "0", unit=ProductUnit.OTHER, tracked=False)

_GENERAL_SHOP = [
    _i("Sukari 1kg", "160", "135"),
    _i("Sukari 500g", "85", "70"),
    _i("Unga wa ugali 2kg", "185", "165"),
    _i("Unga wa ugali 1kg", "95", "85"),
    _i("Unga wa ngano 2kg", "190", "170"),
    _i("Mchele 1kg", "180", "160"),
    _i("Mafuta ya kupikia 1L", "320", "285"),
    _i("Mafuta ya kupikia 500ml", "170", "150"),
    _i("Maziwa 500ml", "65", "55"),
    _i("Mkate 400g", "60", "50"),
    _i("Mayai (1)", "18", "15"),
    _i("Chai (Ketepa 100g)", "120", "105"),
    _i("Kahawa sachet", "10", "8"),
    _i("Chumvi 500g", "30", "25"),
    _i("Royco sachet", "10", "8"),
    _i("Maji 500ml", "30", "22"),
    _i("Soda 500ml", "70", "55"),
    _i("Sabuni ya kufua (bar)", "40", "33"),
    _i("Omo 500g", "150", "130"),
    _i("Sabuni ya kuoga", "60", "48"),
    _i("Tissue roll", "35", "28"),
    _i("Colgate 50ml", "80", "68"),
    _i("Kiberiti", "10", "7"),
    _i("Candle", "20", "15"),
    _i("Blue Band 250g", "160", "140"),
    _i("Pad (pack)", "70", "60"),
    _i("Airtime", "0", unit=ProductUnit.OTHER, tracked=False),
    _OTHER,
]

_BOUTIQUE = [  # beauty, cosmetics, perfumes
    _i("Perfume 50ml", "1500", "1000"),
    _i("Perfume 100ml", "2500", "1700"),
    _i("Body spray", "350", "250"),
    _i("Roll-on", "250", "180"),
    _i("Body lotion 400ml", "450", "330"),
    _i("Petroleum jelly 250ml", "150", "110"),
    _i("Lip gloss", "200", "120"),
    _i("Lipstick", "300", "180"),
    _i("Foundation", "800", "550"),
    _i("Powder", "350", "220"),
    _i("Mascara", "300", "180"),
    _i("Eyeliner", "150", "80"),
    _i("Nail polish", "150", "80"),
    _i("Braids (pack)", "250", "180"),
    _i("Weave", "1500", "1000"),
    _i("Wig", "3500", "2500"),
    _i("Hair oil", "300", "220"),
    _i("Shampoo 400ml", "450", "320"),
    _i("Hair conditioner", "450", "320"),
    _i("Relaxer", "350", "250"),
    _i("Face wash", "400", "280"),
    _i("Sunscreen", "600", "420"),
    _i("Bag", "1200", "800"),
    _i("Earrings", "200", "100"),
    _OTHER,
]

_SALON = [
    _i("Wash and blow", "300", unit=ProductUnit.SERVICE, tracked=False),
    _i("Braiding", "800", unit=ProductUnit.SERVICE, tracked=False),
    _i("Cornrows", "500", unit=ProductUnit.SERVICE, tracked=False),
    _i("Weaving", "1000", unit=ProductUnit.SERVICE, tracked=False),
    _i("Relaxing", "600", unit=ProductUnit.SERVICE, tracked=False),
    _i("Treatment", "500", unit=ProductUnit.SERVICE, tracked=False),
    _i("Haircut (men)", "150", unit=ProductUnit.SERVICE, tracked=False),
    _i("Kids haircut", "100", unit=ProductUnit.SERVICE, tracked=False),
    _i("Shave", "100", unit=ProductUnit.SERVICE, tracked=False),
    _i("Manicure", "300", unit=ProductUnit.SERVICE, tracked=False),
    _i("Pedicure", "400", unit=ProductUnit.SERVICE, tracked=False),
    _i("Gel nails", "800", unit=ProductUnit.SERVICE, tracked=False),
    _i("Braids (pack)", "250", "180"),
    _i("Hair food", "200", "150"),
    _i("Shampoo 400ml", "450", "320"),
    _OTHER,
]

_RESTAURANT = [
    _i("Chai", "30", unit=ProductUnit.SERVICE, tracked=False),
    _i("Mandazi", "20", unit=ProductUnit.SERVICE, tracked=False),
    _i("Chapati", "30", unit=ProductUnit.SERVICE, tracked=False),
    _i("Ugali", "50", unit=ProductUnit.SERVICE, tracked=False),
    _i("Sukuma", "30", unit=ProductUnit.SERVICE, tracked=False),
    _i("Beans", "70", unit=ProductUnit.SERVICE, tracked=False),
    _i("Githeri", "80", unit=ProductUnit.SERVICE, tracked=False),
    _i("Pilau", "150", unit=ProductUnit.SERVICE, tracked=False),
    _i("Rice and beans", "100", unit=ProductUnit.SERVICE, tracked=False),
    _i("Beef stew", "150", unit=ProductUnit.SERVICE, tracked=False),
    _i("Chicken", "250", unit=ProductUnit.SERVICE, tracked=False),
    _i("Fish", "250", unit=ProductUnit.SERVICE, tracked=False),
    _i("Chips", "100", unit=ProductUnit.SERVICE, tracked=False),
    _i("Samosa", "30", unit=ProductUnit.SERVICE, tracked=False),
    _i("Soda 500ml", "70", "55"),
    _i("Maji 500ml", "30", "22"),
    _OTHER,
]

_ELECTRONICS = [
    _i("Phone charger", "300", "180"),
    _i("Earphones", "250", "150"),
    _i("Bluetooth earbuds", "1200", "800"),
    _i("Power bank 10000mAh", "1500", "1000"),
    _i("USB cable", "150", "80"),
    _i("Phone cover", "300", "150"),
    _i("Screen protector", "200", "100"),
    _i("Memory card 32GB", "700", "500"),
    _i("Flash disk 16GB", "600", "420"),
    _i("Bulb LED", "150", "100"),
    _i("Extension cable", "500", "350"),
    _i("Torch", "350", "250"),
    _i("Batteries AA (pair)", "60", "40"),
    _i("Radio", "1500", "1100"),
    _i("Speaker", "2500", "1800"),
    _i("Phone repair", "500", unit=ProductUnit.SERVICE, tracked=False),
    _i("Screen replacement", "2500", unit=ProductUnit.SERVICE, tracked=False),
    _OTHER,
]

STARTER: dict[BusinessType, list[StarterItem]] = {
    BusinessType.GENERAL_SHOP: _GENERAL_SHOP,
    BusinessType.BOUTIQUE: _BOUTIQUE,
    BusinessType.SALON: _SALON,
    BusinessType.RESTAURANT: _RESTAURANT,
    BusinessType.ELECTRONICS: _ELECTRONICS,
    BusinessType.OTHER: [_OTHER],
}


def starter_items(business_type: BusinessType) -> list[StarterItem]:
    return list(STARTER.get(business_type, [_OTHER]))


__all__ = ["STARTER", "StarterItem", "starter_items"]
