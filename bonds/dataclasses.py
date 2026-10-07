from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class AggregatedBondPosition:
    """Агрегированная позиция по облигации со всех счетов."""

    figi: str
    quantity: int
    average_position_price: Decimal
    current_price: Decimal


@dataclass(frozen=True)
class BondInfo:
    """Информация об облигации."""

    name: str
    rating: str
    maturity_date: str
    nominal: str
    amortization: str
    floater: str
    buy_price: str
    quantity: int
    coupons_per_year: int
    next_coupon_before_tax: str
    next_coupon_after_tax: str
    portfolio_percent: str
    yield_to_maturity: str
    coupon_yield_before_tax: str
    coupon_yield_after_tax: str


@dataclass(frozen=True)
class BondPortfolioInfo:
    """Сводная информация по облигационному портфелю."""

    total_quantity: int
    total_invested: Decimal
    current_value: Decimal
    change_percent: Decimal
    coupon_yield_before_tax: Decimal
    coupon_yield_after_tax: Decimal
    yield_to_maturity_before_tax: Decimal
    yield_to_maturity_after_tax: Decimal
