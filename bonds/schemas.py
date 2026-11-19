from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from t_tech.invest.schemas import Bond


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
    company_portfolio_percent: str | None
    yield_to_maturity: str
    coupon_yield_before_tax: str
    coupon_yield_after_tax: str

    def to_dict(self) -> dict:
        """Преобразовать DTO в словарь для JSON."""
        return asdict(self)


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
    annual_income_before_tax: Decimal
    annual_income_after_tax: Decimal
    monthly_income_before_tax: Decimal
    monthly_income_after_tax: Decimal

    def to_dict(self) -> dict:
        """Преобразовать DTO в словарь."""
        data = asdict(self)
        for key, value in data.items():
            if isinstance(value, Decimal):
                data[key] = float(value)
        return data


@dataclass(frozen=True)
class _BondMetrics:
    """
    Сырые метрики по одной облигации.

    Считаются один раз в `BondService._collect_bond_metrics`и переиспользуются в
    `BondService._get_bonds` и `BondService._get_portfolio_info`.
    """

    position: AggregatedBondPosition
    bond: Bond
    next_coupon: Decimal
    ytm_before_tax: Decimal
    ytm_after_tax: Decimal
    coupon_yield_before_tax: Decimal
    coupon_yield_after_tax: Decimal
    annual_coupon_before_tax: Decimal
    annual_coupon_after_tax: Decimal


@dataclass(frozen=True)
class CouponPayment:
    """Купонная выплата по одной облигации."""

    bond_name: str
    quantity: int
    coupon_per_bond: Decimal
    total_amount: Decimal

    def to_dict(self) -> dict:
        """Преобразовать DTO в словарь для JSON."""
        return {
            'bond_name': self.bond_name,
            'quantity': self.quantity,
            'coupon_per_bond': str(self.coupon_per_bond),
            'total_amount': str(self.total_amount),
        }


@dataclass(frozen=True)
class CouponDay:
    """Купонные выплаты за один календарный день."""

    date: date
    label: str
    is_today: bool
    payments: list[CouponPayment]

    def to_dict(self) -> dict:
        """Преобразовать DTO в словарь для JSON."""
        return {
            'date': self.date.isoformat(),
            'label': self.label,
            'is_today': self.is_today,
            'payments': [payment.to_dict() for payment in self.payments],
        }


@dataclass(frozen=True)
class CouponMonth:
    """Сводная информация о купонных выплатах за месяц."""

    year: int
    month: int
    name: str
    is_current_month: bool
    total_amount: Decimal
    days: list[CouponDay]
    paid_amount: Decimal | None = None
    remaining_amount: Decimal | None = None

    def to_dict(self) -> dict:
        """Преобразовать DTO в словарь для JSON."""
        data = {
            'year': self.year,
            'month': self.month,
            'name': self.name,
            'is_current_month': self.is_current_month,
            'total_amount': str(self.total_amount),
            'days': [day.to_dict() for day in self.days],
        }

        if self.is_current_month:
            data.update({
                'paid_amount': str(self.paid_amount),
                'remaining_amount': str(self.remaining_amount),
            })

        return data


@dataclass(frozen=True)
class CouponCalendar:
    """Календарь купонных выплат."""

    current_date: date
    months: list[CouponMonth]

    def to_dict(self) -> dict:
        """Преобразовать DTO в словарь для JSON."""
        return {
            'current_date': self.current_date.isoformat(),
            'months': [month.to_dict() for month in self.months],
        }
