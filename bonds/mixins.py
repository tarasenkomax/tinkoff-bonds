from decimal import Decimal

from t_tech.invest import MoneyValue


class MoneyFormatterMixin:
    NANO_DIVISOR = Decimal(1_000_000_000)

    def _format_money(
        self,
        money: MoneyValue,
    ) -> str:
        """
        Форматирует денежное значение для вывода.

        Args:
            money: Денежное значение T-Tech SDK.

        Returns:
            Строка вида: 1006.00 ₽
        """

        value = self._money_to_decimal(money)

        return f'{value:.2f} ₽'

    def _money_to_decimal(
        self,
        money: MoneyValue,
    ) -> Decimal:
        """
        Конвертирует MoneyValue из SDK в Decimal.

        Args:
            money: Денежное значение T-Tech SDK.

        Returns:
            Денежное значение в виде Decimal.
        """

        return Decimal(money.units) + Decimal(money.nano) / self.NANO_DIVISOR

    def _quotation_to_decimal(
        self,
        quotation,
    ) -> Decimal:
        """
        Конвертирует Quotation из SDK в Decimal.

        Args:
            quotation:
                Значение Quotation из T-Tech SDK.

        Returns:
            Значение в Decimal.
        """

        return Decimal(quotation.units) + Decimal(quotation.nano) / self.NANO_DIVISOR
