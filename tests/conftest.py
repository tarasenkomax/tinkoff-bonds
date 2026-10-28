from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from bonds.adapter import TinkoffInvestAdapter
from bonds.report import BondReport
from bonds.schemas import AggregatedBondPosition, BondInfo, BondPortfolioInfo
from faker import Faker


fake = Faker('ru_RU')


@pytest.fixture
def make_figi():
    """Фабрика уникальных FIGI."""
    def _make() -> str:
        return f'BBG{fake.random_number(digits=6, fix_len=True)}{fake.lexify("????").upper()}'

    return _make


@pytest.fixture
def available_accounts(request) -> list[str]:
    """
    Список доступных счетов.

    По умолчанию — `['acc-1', 'acc-2']`. Тесты могут переопределить
    значение через `@pytest.mark.parametrize(..., indirect=True)`.
    """
    return getattr(request, 'param', ['acc-1', 'acc-2'])


@pytest.fixture
def mock_client(available_accounts: list[str]) -> MagicMock:
    """Мок SDK-клиента с настраиваемым списком доступных счетов."""
    client = MagicMock()
    client.users.get_accounts.return_value = MagicMock(
        accounts=[MagicMock(id=acc_id) for acc_id in available_accounts],
    )
    return client


@pytest.fixture
def make_adapter(mock_client: MagicMock):
    """Фабрика адаптеров для тестов."""
    def _make(
        account_ids: list[str],
        *,
        cache_bonds: bool = True,
        max_workers: int = 8,
    ) -> TinkoffInvestAdapter:
        return TinkoffInvestAdapter(
            client=mock_client,
            account_ids=account_ids,
            max_workers=max_workers,
            cache_bonds=cache_bonds,
        )

    return _make


@pytest.fixture
def make_coupon():
    """
    Фабрика купонов.

    :param days: сдвиг даты купона от «сейчас» в днях (может быть отрицательным)
    :param pay_one_bond_units: размер купона в целых рублях
    """
    def _make(
        days: int = 30,
        *,
        pay_one_bond_units: int = 10,
    ) -> MagicMock:
        coupon = MagicMock()
        coupon.coupon_date = datetime.now(timezone.utc) + timedelta(days=days)
        coupon.pay_one_bond = MagicMock(units=pay_one_bond_units, nano=0)
        return coupon

    return _make


@pytest.fixture
def make_money():
    """Фабрика MoneyValue."""
    def _make(units: int = 0, nano: int = 0) -> MagicMock:
        money = MagicMock()
        money.units = units
        money.nano = nano
        return money

    return _make


@pytest.fixture
def make_bond(make_money):
    """Фабрика Bond из SDK."""
    def _make(
        *,
        name: str | None = None,
        maturity_date: datetime | None = None,
        nominal_units: int = 1000,
        coupon_quantity_per_year: int = 2,
        floating_coupon_flag: bool = False,
        amortization_flag: bool = False,
    ) -> MagicMock:
        bond = MagicMock()
        bond.name = name or fake.company() + ' БО-П01'
        bond.maturity_date = maturity_date or datetime(2040, 10, 3, tzinfo=timezone.utc)
        bond.nominal = make_money(units=nominal_units)
        bond.coupon_quantity_per_year = coupon_quantity_per_year
        bond.floating_coupon_flag = floating_coupon_flag
        bond.amortization_flag = amortization_flag
        return bond

    return _make


@pytest.fixture
def make_position(make_money, make_figi):
    """Фабрика PortfolioPosition из SDK."""
    def _make(
        *,
        figi: str | None = None,
        quantity_units: int = 10,
        average_price_units: int = 900,
        current_price_units: int = 950,
        instrument_type: str = 'bond',
    ) -> MagicMock:
        position = MagicMock()
        position.figi = figi or make_figi()
        position.instrument_type = instrument_type
        position.quantity.units = quantity_units
        position.average_position_price_fifo = make_money(units=average_price_units)
        position.current_price = make_money(units=current_price_units)
        return position

    return _make


@pytest.fixture
def make_aggregated_position(make_figi):
    """Фабрика AggregatedBondPosition."""
    def _make(
        *,
        figi: str | None = None,
        quantity: int = 10,
        average_position_price: Decimal = Decimal('900'),
        current_price: Decimal = Decimal('950'),
    ) -> AggregatedBondPosition:
        return AggregatedBondPosition(
            figi=figi or make_figi(),
            quantity=quantity,
            average_position_price=average_position_price,
            current_price=current_price,
        )

    return _make


@pytest.fixture
def make_adapter_mock():
    """Мок TinkoffInvestAdapter с настраиваемыми ответами."""
    def _make(
        *,
        portfolios: list[MagicMock] | None = None,
        bonds_by_figi: dict[str, MagicMock | None] | None = None,
        next_coupons_by_figi: dict[str, MagicMock | None] | None = None,
    ) -> MagicMock:
        adapter = MagicMock()
        adapter.get_portfolios.return_value = portfolios or []
        adapter.get_bond_by_figi.side_effect = lambda figi: (bonds_by_figi or {}).get(figi)
        adapter.get_next_bond_coupon.side_effect = lambda figi: (next_coupons_by_figi or {}).get(figi)
        return adapter

    return _make


@pytest.fixture
def make_portfolio():
    """Фабрика PortfolioResponse с набором позиций."""
    def _make(*positions: MagicMock) -> MagicMock:
        portfolio = MagicMock()
        portfolio.positions = list(positions)
        return portfolio

    return _make


@pytest.fixture
def make_report() -> BondReport:
    """Фабрика отчета (возвращает готовый экземпляр)."""
    return BondReport()


@pytest.fixture
def make_bond_info():
    """
    Фабрика DTO с информацией об облигации.

    :param name: название (по умолчанию генерируется)
    :param rating: рейтинг (по умолчанию генерируется)
    :param portfolio_percent: доля облигации (строка, например "2.00%")
    :param company_portfolio_percent: доля компании (строка или None)
    """
    def _make(
        *,
        name: str | None = None,
        rating: str | None = None,
        maturity_date: str = '03.10.2040',
        nominal: str = '1000.00 ₽',
        amortization: str = '-',
        floater: str = '-',
        buy_price: str = '900.00 ₽',
        quantity: int | None = None,
        coupons_per_year: int | None = None,
        next_coupon_before_tax: str = '30.00 ₽',
        next_coupon_after_tax: str = '26.10 ₽',
        portfolio_percent: str = '2.50%',
        company_portfolio_percent: str | None = None,
        yield_to_maturity: str = '15.12% / 13.15%',
        coupon_yield_before_tax: str = '14.22%',
        coupon_yield_after_tax: str = '12.37%',
    ) -> BondInfo:
        return BondInfo(
            name=name or f'{fake.company()} БО-П{fake.random_int(1, 99):02d}',
            rating=rating or fake.random_element(elements=('AAA', 'AA+', 'A', 'BBB+', 'BBB-')),
            maturity_date=maturity_date,
            nominal=nominal,
            amortization=amortization,
            floater=floater,
            buy_price=buy_price,
            quantity=quantity or fake.random_int(1, 100),
            coupons_per_year=coupons_per_year or fake.random_int(1, 12),
            next_coupon_before_tax=next_coupon_before_tax,
            next_coupon_after_tax=next_coupon_after_tax,
            portfolio_percent=portfolio_percent,
            company_portfolio_percent=company_portfolio_percent,
            yield_to_maturity=yield_to_maturity,
            coupon_yield_before_tax=coupon_yield_before_tax,
            coupon_yield_after_tax=coupon_yield_after_tax,
        )

    return _make


@pytest.fixture
def make_portfolio_info():
    """
    Фабрика DTO со сводной информацией по портфелю.
    """
    def _make(
        *,
        total_quantity: int = 100,
        total_invested: Decimal = Decimal('100000'),
        current_value: Decimal = Decimal('105000'),
        change_percent: Decimal = Decimal('5.00'),
        coupon_yield_before_tax: Decimal = Decimal('15.00'),
        coupon_yield_after_tax: Decimal = Decimal('13.05'),
        yield_to_maturity_before_tax: Decimal = Decimal('16.00'),
        yield_to_maturity_after_tax: Decimal = Decimal('13.92'),
        annual_income_before_tax: Decimal = Decimal('15000'),
        annual_income_after_tax: Decimal = Decimal('13050'),
        monthly_income_before_tax: Decimal = Decimal('1250'),
        monthly_income_after_tax: Decimal = Decimal('1087.50'),
    ) -> BondPortfolioInfo:
        return BondPortfolioInfo(
            total_quantity=total_quantity,
            total_invested=total_invested,
            current_value=current_value,
            change_percent=change_percent,
            coupon_yield_before_tax=coupon_yield_before_tax,
            coupon_yield_after_tax=coupon_yield_after_tax,
            yield_to_maturity_before_tax=yield_to_maturity_before_tax,
            yield_to_maturity_after_tax=yield_to_maturity_after_tax,
            annual_income_before_tax=annual_income_before_tax,
            annual_income_after_tax=annual_income_after_tax,
            monthly_income_before_tax=monthly_income_before_tax,
            monthly_income_after_tax=monthly_income_after_tax,
        )

    return _make
