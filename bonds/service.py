from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from t_tech.invest.schemas import Bond, PortfolioPosition

from .adapter import TinkoffInvestAdapter
from .dataclasses import BondInfo, BondPortfolioInfo
from .mixins import MoneyFormatterMixin


class BondService(MoneyFormatterMixin):
    """
    Сервис получения информации об облигациях пользователя.
    """

    TAX_RATE = Decimal("0.13")

    def __init__(
        self,
        adapter: TinkoffInvestAdapter,
    ) -> None:
        """
        Args:
            adapter: Адаптер Tinkoff Invest.
        """

        self._adapter = adapter

    def _get_bonds_portfolio(
        self,
    ) -> list[PortfolioPosition]:
        """
        Получает только облигационную часть портфеля.

        Returns:
            Список позиций облигаций.
        """

        portfolio = self._adapter.get_portfolio()

        return [
            position
            for position in portfolio.positions
            if self._is_bond(position)
        ]

    def get_bonds(self) -> list[BondInfo]:
        """
        Возвращает список облигаций пользователя.

        Returns:
            Список облигаций портфеля, отсортированный по названию.
        """

        bond_positions = self._get_bonds_portfolio()

        total_bonds_quantity = sum(
            position.quantity.units
            for position in bond_positions
        )

        bonds: list[BondInfo] = []

        for position in bond_positions:
            bond = self._adapter.get_bond_by_figi(position.figi)

            bonds.append(
                self._create_bond_info(
                    bond=bond,
                    position=position,
                    total_bonds_quantity=(
                        total_bonds_quantity
                    ),
                )
            )

        return sorted(
            bonds,
            key=lambda bond: bond.name.lower(),
        )

    @staticmethod
    def _is_bond(
        position: PortfolioPosition,
    ) -> bool:
        """
        Проверяет, является ли позиция облигацией.

        Args:
            position: Позиция портфеля.

        Returns:
            True, если позиция является облигацией, иначе False.
        """

        return position.instrument_type == "bond"

    @staticmethod
    def _calculate_position_percent(
        position: PortfolioPosition,
        total_bonds_quantity: int,
    ) -> Decimal:
        """
        Рассчитывает долю облигации в портфеле по количеству бумаг.

        Args:
            position: Позиция облигации.
            total_bonds_quantity: Общее количество облигаций в портфеле.

        Returns:
            Процент облигаций данного выпуска от общего количества облигаций.
        """

        if total_bonds_quantity == 0:
            return Decimal("0")

        return Decimal(position.quantity.units) / Decimal(total_bonds_quantity) * Decimal("100")

    def _calculate_yield_to_maturity(
        self,
        bond: Bond,
        position: PortfolioPosition,
        coupon: Decimal,
    ) -> Decimal:
        """
        Рассчитывает приблизительную доходность облигации
        к погашению.

        Формула:
            (годовой купон + (номинал - цена) / лет до погашения)
            / цена * 100

        Args:
            bond:
                Информация об облигации.

            position:
                Позиция пользователя.

        Returns:
            Доходность в процентах.
        """

        if not bond.maturity_date:
            return Decimal("0")

        price = self._money_to_decimal(position.average_position_price)

        nominal = self._money_to_decimal(bond.nominal)

        if price <= 0:
            return Decimal("0")

        now = datetime.now(timezone.utc)

        years_to_maturity = Decimal(
            (bond.maturity_date - now).days
        ) / Decimal("365")

        if years_to_maturity <= 0:
            return Decimal("0")

        coupons_per_year = Decimal(bond.coupon_quantity_per_year)

        annual_coupon = (coupon * coupons_per_year)

        redemption_gain = (nominal - price) / years_to_maturity

        ytm = (annual_coupon + redemption_gain) / price

        return ytm * Decimal("100")

    def _calculate_coupon_yield_before_tax(
        self,
        bond: Bond,
        position: PortfolioPosition,
        next_coupon: Decimal,
    ) -> Decimal:
        """
        Рассчитывает текущую доходность облигации до вычета налогов.

        Формула:
            (годовой купон / цена покупки) * 100

        Args:
            bond:
                Информация об облигации.

            position:
                Позиция пользователя.

        Returns:
            Текущая доходность в процентах.
        """

        price = self._money_to_decimal(position.average_position_price)

        if price <= 0:
            return Decimal("0")

        if next_coupon <= 0:
            return Decimal("0")

        annual_coupon = next_coupon * Decimal(bond.coupon_quantity_per_year)

        return annual_coupon / price * Decimal("100")

    def _calculate_coupon_yield_after_tax(
        self,
        bond: Bond,
        position: PortfolioPosition,
        next_coupon: Decimal,
    ) -> Decimal:
        """
        Рассчитывает текущую доходность облигации после вычета НДФЛ.

        Формула:
            (годовой купон после НДФЛ / цена покупки) * 100

        Args:
            bond:
                Информация об облигации.

            position:
                Позиция пользователя.

        Returns:
            Текущая доходность после НДФЛ в процентах.
        """

        price = self._money_to_decimal(position.average_position_price)

        if price <= 0:
            return Decimal("0")

        if next_coupon <= 0:
            return Decimal("0")

        annual_coupon = self._calculate_coupon_after_tax(next_coupon) * Decimal(bond.coupon_quantity_per_year)

        return annual_coupon / price * Decimal("100")

    def _get_next_coupon(
        self,
        figi: str,
    ) -> Decimal:
        """
        Получает размер ближайшего купона на одну облигацию.

        Args:
            figi: FIGI облигации.

        Returns:
            Сумма ближайшего купона.
        """

        coupon = self._adapter.get_next_bond_coupon(figi)

        if coupon is None:
            return Decimal("0")

        return self._money_to_decimal(coupon.pay_one_bond)

    def _calculate_coupon_after_tax(
        self,
        coupon: Decimal,
    ) -> Decimal:
        """
        Рассчитывает купон после налога.

        Args:
            coupon: Купон до налога.

        Returns:
            Купон после налога.
        """

        return coupon * (Decimal("1") - self.TAX_RATE)

    def _create_bond_info(
        self,
        bond: Bond,
        position: PortfolioPosition,
        total_bonds_quantity: int,
    ) -> BondInfo:
        """
        Формирует DTO облигации.

        Args:
            bond: Информация об облигации.
            position: Позиция облигации в портфеле.
            total_bonds_quantity: Общее количество облигаций в портфеле.

        Returns:
            BondInfo.
        """

        next_coupon = self._get_next_coupon(position.figi)
        ytm = self._calculate_yield_to_maturity(bond=bond, position=position, coupon=next_coupon)
        coupon_yield_before = self._calculate_coupon_yield_before_tax(bond, position, next_coupon)
        coupon_yield_after = self._calculate_coupon_yield_after_tax(bond, position, next_coupon)
        coupon_after_tax = self._calculate_coupon_after_tax(next_coupon)

        return BondInfo(
            name=bond.name,
            rating="-",
            maturity_date=bond.maturity_date.strftime("%d.%m.%Y") if bond.maturity_date else "-",
            nominal=self._format_money(bond.nominal),
            amortization="+" if bond.amortization_flag else "-",
            floater="+" if bond.floating_coupon_flag else "-",
            buy_price=self._format_money(position.average_position_price),
            quantity=position.quantity.units,
            coupons_per_year=bond.coupon_quantity_per_year,
            next_coupon=   f"{next_coupon:.2f} ₽ / {coupon_after_tax:.2f} ₽",
            portfolio_percent=f"{self._calculate_position_percent(position, total_bonds_quantity):.2f}%",
            yield_to_maturity=(f"~{ytm:.2f}%" if bond.floating_coupon_flag else f"{ytm:.2f}%"),
            coupon_yield=f"{coupon_yield_before:.2f}% / {coupon_yield_after:.2f}%",
        )

    def get_portfolio_info(
        self,
    ) -> BondPortfolioInfo:
        """
        Возвращает сводную информацию по облигационному портфелю.

        Returns:
            Сводная информация по облигациям.
        """

        bond_positions = self._get_bonds_portfolio()

        total_quantity = sum(
            position.quantity.units
            for position in bond_positions
        )

        total_invested = sum(
            self._money_to_decimal(position.average_position_price) * Decimal(position.quantity.units)
            for position in bond_positions
        )

        current_value = sum(
            self._money_to_decimal(position.current_price) * Decimal(position.quantity.units)
            for position in bond_positions
        )

        change_percent = (
            self._calculate_portfolio_change_percent(
                invested=total_invested,
                current_value=current_value,
            )
        )

        return BondPortfolioInfo(
            total_quantity=total_quantity,
            total_invested=total_invested,
            current_value=current_value,
            change_percent=change_percent,
        )

    def _calculate_portfolio_change_percent(
        self,
        invested: Decimal,
        current_value: Decimal,
    ) -> Decimal:
        """
        Рассчитывает изменение стоимости портфеля
        относительно вложенной суммы.

        Args:
            invested:
                Сумма вложений.

            current_value:
                Текущая стоимость портфеля.

        Returns:
            Изменение в процентах.
        """
        if invested == Decimal("0"):
            return Decimal("0")

        return (current_value - invested) / invested * Decimal("100")
