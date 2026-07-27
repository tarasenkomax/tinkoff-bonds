from __future__ import annotations

from decimal import Decimal

from t_tech.invest.schemas import Bond, PortfolioPosition

from .adapter import TinkoffInvestAdapter
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
            next_coupon_before_tax=f"{next_coupon:.2f} ₽",
            next_coupon_after_tax=f"{self._calculate_coupon_after_tax(next_coupon):.2f} ₽",
            portfolio_percent=f"{self._calculate_position_percent(position, total_bonds_quantity):.2f}%",
            # yield_to_maturity=f"{self._quotation_to_decimal(bond.yield_to_maturity):.2f}%" if bond.yield_to_maturity else "-",
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

        return (current_value - invested) / invested * Decimal("100")
