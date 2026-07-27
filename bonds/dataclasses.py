from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BondInfo:
    """
    DTO с информацией об облигации.
    """

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

    # yield_to_maturity: str


@dataclass(frozen=True)
class BondPortfolioInfo:
    """
    Сводная информация по облигационному портфелю.
    """

    total_quantity: int
    total_invested: Decimal
    current_value: Decimal
    change_percent: Decimal