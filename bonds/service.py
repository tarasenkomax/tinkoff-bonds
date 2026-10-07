from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from t_tech.invest.schemas import Bond, PortfolioPosition

from .adapter import TinkoffInvestAdapter
from .mixins import MoneyFormatterMixin
from .schemas import AggregatedBondPosition, BondInfo, BondPortfolioInfo


class BondService(MoneyFormatterMixin):
    """Сервис получения информации об облигациях пользователя."""

    TAX_RATE = Decimal('0.13')

    def __init__(self, adapter: TinkoffInvestAdapter) -> None:
        self._adapter = adapter

    def _get_bonds_portfolio(
        self,
    ) -> list[AggregatedBondPosition]:
        """
        Возвращает агрегированные позиции по облигациям
        со всех брокерских счетов.
        """

        portfolios = self._adapter.get_portfolios()

        positions = [
            position for portfolio in portfolios for position in portfolio.positions if self._is_bond(position)
        ]

        return self._aggregate_positions(positions)

    def _aggregate_positions(
        self,
        positions: list[PortfolioPosition],
    ) -> list[AggregatedBondPosition]:
        """
        Объединяет позиции одной облигации со всех счетов.

        Позиции группируются по FIGI.

        Количество облигаций складывается.
        Цена покупки рассчитывается как средневзвешенная
        по количеству.
        Текущая цена рассчитывается как средневзвешенная
        по количеству.

        Args:
            positions:
                Позиции облигаций со всех счетов.

        Returns:
            Список агрегированных позиций.
        """

        grouped: dict[str, list[PortfolioPosition]] = defaultdict(list)

        for position in positions:
            grouped[position.figi].append(position)

        result: list[AggregatedBondPosition] = []

        for figi, figi_positions in grouped.items():
            total_quantity = sum(position.quantity.units for position in figi_positions)

            if total_quantity == 0:
                continue

            total_invested = sum(
                self._money_to_decimal(position.average_position_price_fifo) * Decimal(position.quantity.units)
                for position in figi_positions
            )

            total_current_value = sum(
                self._money_to_decimal(position.current_price) * Decimal(position.quantity.units)
                for position in figi_positions
            )

            total_quantity_decimal = Decimal(total_quantity)

            result.append(
                AggregatedBondPosition(
                    figi=figi,
                    quantity=total_quantity,
                    average_position_price=(total_invested / total_quantity_decimal),
                    current_price=(total_current_value / total_quantity_decimal),
                ),
            )

        return result

    def get_bonds(self) -> list[BondInfo]:
        """
        Возвращает информацию обо всех облигациях
        со всех брокерских счетов.
        """

        bond_positions = self._get_bonds_portfolio()

        total_bonds_quantity = sum(position.quantity for position in bond_positions)

        bonds: list[BondInfo] = []

        for position in bond_positions:
            bond = self._adapter.get_bond_by_figi(position.figi)

            bonds.append(
                self._create_bond_info(
                    bond=bond,
                    position=position,
                    total_bonds_quantity=total_bonds_quantity,
                ),
            )

        return sorted(
            bonds,
            key=lambda bond: bond.name.lower(),
        )

    @staticmethod
    def _is_bond(position: PortfolioPosition) -> bool:
        """Проверяет, является ли позиция облигацией."""

        return position.instrument_type == 'bond'

    @staticmethod
    def _calculate_position_percent(
        position: AggregatedBondPosition,
        total_bonds_quantity: int,
    ) -> Decimal:
        """
        Рассчитывает долю облигации в портфеле.

        Доля рассчитывается по количеству облигаций,
        а не по их стоимости.
        """

        if total_bonds_quantity == 0:
            return Decimal('0')

        return Decimal(position.quantity) / Decimal(total_bonds_quantity) * Decimal('100')

    def _calculate_yield_to_maturity(
        self,
        bond: Bond,
        position: AggregatedBondPosition,
        coupon: Decimal,
        after_tax: bool = False,
    ) -> Decimal:
        """
        Рассчитывает приблизительную доходность облигации
        к погашению.

        Доходность рассчитывается по упрощённой формуле:

            (годовой купон + (номинал - цена) / лет до погашения)
            / цена * 100

        При after_tax=True годовой купон рассчитывается
        с учётом НДФЛ по ставке TAX_RATE. Доход от разницы
        между ценой покупки и номиналом при этом не изменяется.

        Args:
            bond:
                Информация об облигации, включая номинал,
                дату погашения и количество купонных выплат в год.

            position:
                Агрегированная позиция пользователя.

            coupon:
                Размер купона на одну облигацию до уплаты НДФЛ.

            after_tax:
                Если True, рассчитывает доходность с учётом НДФЛ
                на купонный доход. По умолчанию False.

        Returns:
            Приблизительная доходность облигации к погашению
            в процентах.
        """

        if not bond.maturity_date:
            return Decimal('0')

        price = position.average_position_price
        nominal = self._money_to_decimal(bond.nominal)

        if price <= 0:
            return Decimal('0')

        now = datetime.now(timezone.utc)

        years_to_maturity = Decimal((bond.maturity_date - now).days) / Decimal('365')

        if years_to_maturity <= 0:
            return Decimal('0')

        if after_tax:
            coupon = self._calculate_coupon_after_tax(coupon)

        coupons_per_year = Decimal(bond.coupon_quantity_per_year)
        annual_coupon = coupon * coupons_per_year
        redemption_gain = (nominal - price) / years_to_maturity
        ytm = (annual_coupon + redemption_gain) / price

        return ytm * Decimal('100')

    def _calculate_coupon_yield_before_tax(
        self,
        bond: Bond,
        position: AggregatedBondPosition,
        next_coupon: Decimal,
    ) -> Decimal:
        """Рассчитывает текущую купонную доходность до НДФЛ."""

        price = position.average_position_price

        if price <= 0 or next_coupon <= 0:
            return Decimal('0')

        annual_coupon = next_coupon * Decimal(bond.coupon_quantity_per_year)

        return annual_coupon / price * Decimal('100')

    def _calculate_coupon_yield_after_tax(
        self,
        bond: Bond,
        position: AggregatedBondPosition,
        next_coupon: Decimal,
    ) -> Decimal:
        """Рассчитывает текущую купонную доходность после НДФЛ."""

        price = position.average_position_price

        if price <= 0 or next_coupon <= 0:
            return Decimal('0')

        annual_coupon = self._calculate_coupon_after_tax(next_coupon) * Decimal(bond.coupon_quantity_per_year)

        return annual_coupon / price * Decimal('100')

    def _calculate_irr(
        self,
        price: Decimal,
        cash_flows: list[tuple[Decimal, Decimal]],
    ) -> Decimal:
        """Рассчитывает IRR методом Ньютона."""

        rate = Decimal('0.15')

        for _ in range(100):
            value = Decimal('0')
            derivative = Decimal('0')

            for years, amount in cash_flows:
                denominator = (Decimal('1') + rate)**years
                value += amount / denominator
                derivative -= years * amount / (Decimal('1') + rate)**(years + Decimal('1'))

            diff = value - price

            if abs(diff) < Decimal('0.000001'):
                return rate

            if derivative == 0:
                break

            rate -= diff / derivative

        return rate

    def _get_next_coupon(
        self,
        figi: str,
    ) -> Decimal:
        """
        Возвращает размер ближайшего купона.

        Если ближайший купон отсутствует, возвращает 0.
        """

        coupon = self._adapter.get_next_bond_coupon(figi)

        if coupon is None:
            return Decimal('0')

        return self._money_to_decimal(coupon.pay_one_bond)

    def _calculate_coupon_after_tax(
        self,
        coupon: Decimal,
    ) -> Decimal:
        """Рассчитывает купон после НДФЛ."""

        return coupon * (Decimal('1') - self.TAX_RATE)

    def _create_bond_info(
        self,
        bond: Bond,
        position: AggregatedBondPosition,
        total_bonds_quantity: int,
    ) -> BondInfo:
        """Создаёт DTO с информацией об облигации."""

        next_coupon = self._get_next_coupon(position.figi)

        ytm_before_tax = self._calculate_yield_to_maturity(
            bond=bond,
            position=position,
            coupon=next_coupon,
        )

        ytm_after_tax = self._calculate_yield_to_maturity(
            bond=bond,
            position=position,
            coupon=next_coupon,
            after_tax=True,
        )

        coupon_yield_before_tax = self._calculate_coupon_yield_before_tax(
            bond=bond,
            position=position,
            next_coupon=next_coupon,
        )

        coupon_yield_after_tax = self._calculate_coupon_yield_after_tax(
            bond=bond,
            position=position,
            next_coupon=next_coupon,
        )

        ytm_prefix = '~' if bond.floating_coupon_flag else ''

        return BondInfo(
            name=bond.name,
            rating='-',
            maturity_date=bond.maturity_date.strftime('%d.%m.%Y') if bond.maturity_date else '-',
            nominal=self._format_money(bond.nominal),
            amortization='+' if bond.amortization_flag else '-',
            floater='+' if bond.floating_coupon_flag else '-',
            buy_price=f'{position.average_position_price:.2f} ₽',
            quantity=position.quantity,
            coupons_per_year=bond.coupon_quantity_per_year,
            next_coupon_before_tax=f'{next_coupon:.2f} ₽',
            next_coupon_after_tax=f'{self._calculate_coupon_after_tax(next_coupon):.2f} ₽',
            portfolio_percent=f'{self._calculate_position_percent(position, total_bonds_quantity, ):.2f}%',
            yield_to_maturity=f'{ytm_prefix}{ytm_before_tax:.2f}% / {ytm_prefix}{ytm_after_tax:.2f}%',
            coupon_yield_before_tax=f'{coupon_yield_before_tax:.2f}%',
            coupon_yield_after_tax=f'{coupon_yield_after_tax:.2f}%',
        )

    def get_portfolio_info(self) -> BondPortfolioInfo:
        """
        Возвращает сводную информацию по облигационному портфелю.

        В расчёте участвуют облигации со всех брокерских счетов.
        """

        bond_positions = self._get_bonds_portfolio()
        total_quantity = sum(position.quantity for position in bond_positions)
        total_invested = sum(
            position.average_position_price * Decimal(position.quantity) for position in bond_positions
        )
        current_value = sum(position.current_price * Decimal(position.quantity) for position in bond_positions)
        change_percent = self._calculate_portfolio_change_percent(invested=total_invested, current_value=current_value)
        total_coupon_income_before_tax = Decimal('0')
        total_coupon_income_after_tax = Decimal('0')
        weighted_ytm_before_tax = Decimal('0')
        weighted_ytm_after_tax = Decimal('0')

        for position in bond_positions:
            bond = self._adapter.get_bond_by_figi(position.figi)
            price = position.average_position_price
            quantity = Decimal(position.quantity)
            coupon = self._get_next_coupon(position.figi)

            if price <= 0:
                continue

            annual_coupon_before_tax = coupon * Decimal(bond.coupon_quantity_per_year)
            annual_coupon_after_tax = self._calculate_coupon_after_tax(coupon) * Decimal(bond.coupon_quantity_per_year)
            total_coupon_income_before_tax += annual_coupon_before_tax * quantity
            total_coupon_income_after_tax += annual_coupon_after_tax * quantity
            ytm_before_tax = self._calculate_yield_to_maturity(
                bond=bond,
                position=position,
                coupon=coupon,
            )

            ytm_after_tax = self._calculate_yield_to_maturity(
                bond=bond,
                position=position,
                coupon=coupon,
                after_tax=True,
            )

            invested_amount = price * quantity
            weighted_ytm_before_tax += ytm_before_tax * invested_amount
            weighted_ytm_after_tax += ytm_after_tax * invested_amount

        coupon_yield_before_tax = (
            total_coupon_income_before_tax / total_invested * Decimal('100') if total_invested > 0 else Decimal('0')
        )

        coupon_yield_after_tax = (
            total_coupon_income_after_tax / total_invested * Decimal('100') if total_invested > 0 else Decimal('0')
        )

        portfolio_ytm_before_tax = weighted_ytm_before_tax / total_invested if total_invested > 0 else Decimal('0')
        portfolio_ytm_after_tax = weighted_ytm_after_tax / total_invested if total_invested > 0 else Decimal('0')

        return BondPortfolioInfo(
            total_quantity=total_quantity,
            total_invested=total_invested,
            current_value=current_value,
            change_percent=change_percent,
            coupon_yield_before_tax=coupon_yield_before_tax,
            coupon_yield_after_tax=coupon_yield_after_tax,
            yield_to_maturity_before_tax=portfolio_ytm_before_tax,
            yield_to_maturity_after_tax=portfolio_ytm_after_tax,
        )

    @staticmethod
    def _calculate_portfolio_change_percent(
        invested: Decimal,
        current_value: Decimal,
    ) -> Decimal:
        """Рассчитывает изменение стоимости портфеля в процентах."""

        if invested <= 0:
            return Decimal('0')

        return (current_value - invested) / invested * Decimal('100')
