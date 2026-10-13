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
        Вернуть агрегированные позиции по облигациям со всех счетов.

        :return: список агрегированных позиций по облигациям
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
        Объединить позиции одной облигации со всех счетов.

        Позиции группируются по FIGI. Количество облигаций
        складывается. Цена покупки и текущая цена рассчитываются
        как средневзвешенные по количеству.

        :param positions: позиции облигаций со всех счетов
        :return: список агрегированных позиций
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
        Вернуть информацию обо всех облигациях со всех счетов.

        :return: список облигаций, отсортированный по имени
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
        """
        Проверить, является ли позиция облигацией.

        :param position: позиция портфеля
        :return: `True`, если позиция — облигация
        """

        return position.instrument_type == 'bond'

    @staticmethod
    def _calculate_position_percent(
        position: AggregatedBondPosition,
        total_bonds_quantity: int,
    ) -> Decimal:
        """
        Рассчитать долю облигации в портфеле.

        Доля считается по количеству облигаций, а не по стоимости.

        :param position: агрегированная позиция
        :param total_bonds_quantity: суммарное количество облигаций в портфеле
        :return: доля облигации в процентах
        """

        return Decimal(position.quantity) / Decimal(total_bonds_quantity) * Decimal('100')

    def _calculate_yield_to_maturity(
        self,
        bond: Bond,
        position: AggregatedBondPosition,
        coupon: Decimal,
        after_tax: bool = False,
    ) -> Decimal:
        """
        Рассчитать приблизительную доходность облигации к погашению.

        Доходность рассчитывается по упрощённой формуле:
            (годовой купон + (номинал − цена) / лет до погашения) / цена * 100

        При `after_tax=True` годовой купон рассчитывается с учётом НДФЛ по ставке `TAX_RATE`. Доход от разницы между
        ценой покупки и номиналом при этом не изменяется.

        :param bond: информация об облигации, включая номинал, дату погашения и количество купонных выплат в год
        :param position: агрегированная позиция пользователя
        :param coupon: размер купона на одну облигацию до уплаты НДФЛ
        :param after_tax: если `True`, рассчитывает доходность с учётом НДФЛ на купонный доход
        :return: приблизительная доходность к погашению в процентах
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
        """
        Рассчитать текущую купонную доходность до НДФЛ.

        :param bond: информация об облигации
        :param position: агрегированная позиция пользователя
        :param next_coupon: размер ближайшего купона
        :return: купонная доходность в процентах
        """

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
        """
        Рассчитать текущую купонную доходность после НДФЛ.

        :param bond: информация об облигации
        :param position: агрегированная позиция пользователя
        :param next_coupon: размер ближайшего купона
        :return: купонная доходность в процентах
        """

        price = position.average_position_price

        if price <= 0 or next_coupon <= 0:
            return Decimal('0')

        annual_coupon = self._calculate_coupon_after_tax(next_coupon) * Decimal(bond.coupon_quantity_per_year)

        return annual_coupon / price * Decimal('100')

    def _get_next_coupon(
        self,
        figi: str,
    ) -> Decimal:
        """
        Вернуть размер ближайшего купона.

        :param figi: FIGI облигации
        :return: размер ближайшего купона или `0`, если купона нет
        """

        coupon = self._adapter.get_next_bond_coupon(figi)

        if coupon is None:
            return Decimal('0')

        return self._money_to_decimal(coupon.pay_one_bond)

    def _calculate_coupon_after_tax(
        self,
        coupon: Decimal,
    ) -> Decimal:
        """
        Рассчитать купон после НДФЛ.

        :param coupon: размер купона до налога
        :return: размер купона после удержания НДФЛ
        """

        return coupon * (Decimal('1') - self.TAX_RATE)

    def _create_bond_info(
        self,
        bond: Bond,
        position: AggregatedBondPosition,
        total_bonds_quantity: int,
    ) -> BondInfo:
        """
        Создать DTO с информацией об облигации.

        :param bond: информация об облигации из SDK
        :param position: агрегированная позиция пользователя
        :param total_bonds_quantity: суммарное количество облигаций в портфеле (для расчёта доли)
        :return: DTO с информацией об облигации
        """

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
        Вернуть сводную информацию по облигационному портфелю.

        В расчёте участвуют облигации со всех брокерских счетов.

        :return: DTO со сводной информацией по портфелю
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
        """
        Рассчитать изменение стоимости портфеля в процентах.

        :param invested: сумма вложений
        :param current_value: текущая стоимость портфеля
        :return: изменение стоимости в процентах
        """

        if invested <= 0:
            return Decimal('0')

        return (current_value - invested) / invested * Decimal('100')
