from datetime import datetime
from decimal import Decimal

from bonds.schemas import BondInfo, BondPortfolioInfo


class BondReport:
    """Класс для форматирования и вывода отчета по облигациям в консоль."""

    COLOR_GREEN = '\033[32m'
    COLOR_RED = '\033[31m'
    COLOR_RESET = '\033[0m'
    COLOR_YELLOW = '\033[33m'
    COLOR_LIGHT_YELLOW = '\033[93m'

    INDEX_WIDTH = 5
    NAME_WIDTH = 32
    RATING_WIDTH = 10
    MATURITY_WIDTH = 12
    NOMINAL_WIDTH = 14
    AMORTIZATION_WIDTH = 8
    FLOATER_WIDTH = 10
    BUY_PRICE_WIDTH = 15
    QUANTITY_WIDTH = 8
    COUPONS_WIDTH = 10
    COUPON_WIDTH = 22
    PORTFOLIO_WIDTH = 18
    CURRENT_YIELD_WIDTH = 29
    YTM_WIDTH = 10

    BONDS_TABLE_HEADER = (
        f"{'№':<{INDEX_WIDTH}}"
        f"{'Название':<{NAME_WIDTH}}"
        f"{'Рейтинг':<{RATING_WIDTH}}"
        f"{'Погашение':<{MATURITY_WIDTH}}"
        f"{'Номинал':<{NOMINAL_WIDTH}}"
        f"{'Аморт.':<{AMORTIZATION_WIDTH}}"
        f"{'Флоатер':<{FLOATER_WIDTH}}"
        f"{'Покупка':<{BUY_PRICE_WIDTH}}"
        f"{'Кол-во':<{QUANTITY_WIDTH}}"
        f"{'Куп./год':<{COUPONS_WIDTH}}"
        f"{'Купон (до/после)':<{COUPON_WIDTH}}"
        f"{'% портфеля':<{PORTFOLIO_WIDTH}}"
        f"{'Куп. доходность (до/после)':<{CURRENT_YIELD_WIDTH}}"
        f"{'YTM (до/после)':<{YTM_WIDTH}}"
    )

    @staticmethod
    def _format_percent(value: Decimal) -> str:
        """
        Отформатировать процент с явным знаком.

        :param value: значение в процентах
        :return: строка вида `+0.12%` или `-3.45%`
        """
        return f'{value:+.2f}%'

    @staticmethod
    def _format_decimal_ru(value: Decimal) -> str:
        """
        Отформатировать `Decimal` в российский формат.

        :param value: числовое значение
        :return: строка вида `1.234.567,89`
        """
        return f'{value:,.2f}'.replace(',', ' ').replace('.', ',').replace(' ', '.')

    def _colorize(self, text: str, color: str, width: int) -> str:
        """
        Раскрасить текст, сохранив выравнивание по ширине.

        :param text: исходный текст
        :param color: ANSI-код цвета
        :param width: ширина поля
        :return: отформатированная и раскрашенная строка
        """
        padded = f'{text:<{width}}'
        if not color:
            return padded
        return padded.replace(text, f'{color}{text}{self.COLOR_RESET}')

    def _format_maturity(self, maturity_date: str) -> str:
        """Раскрасить дату погашения в зависимости от года."""
        color = ''
        if maturity_date and maturity_date != '-':
            maturity_dt = datetime.strptime(maturity_date, '%d.%m.%Y')
            current_year = datetime.now().year
            if maturity_dt.year == current_year:
                color = self.COLOR_LIGHT_YELLOW
            elif maturity_dt.year == current_year + 1:
                color = self.COLOR_YELLOW

        return self._colorize(maturity_date, color, self.MATURITY_WIDTH)

    def _format_buy_price(self, buy_price: str, nominal: str) -> str:
        """Раскрасить цену покупки (зелёный — ниже номинала, красный — выше)."""
        color = ''

        buy_val = Decimal(buy_price.replace(' ₽', '').replace(' ', ''))
        nom_val = Decimal(nominal.replace(' ₽', '').replace(' ', ''))
        if buy_val < nom_val:
            color = self.COLOR_GREEN
        elif buy_val > nom_val:
            color = self.COLOR_RED

        return self._colorize(buy_price, color, self.BUY_PRICE_WIDTH)

    def _format_portfolio_percent(self, bond: BondInfo) -> str:
        """
        Раскрасить долю портфеля.

        Красный цвет применяется независимо к проценту облигации и проценту компании, если они > 5%.

        :param bond: информация об облигации
        :return: отформатированная строка для вывода
        """

        bond_text = bond.portfolio_percent
        bond_color = ''

        val = Decimal(bond_text.replace('%', '').replace(' ', ''))
        if val > 5.0:
            bond_color = self.COLOR_RED

        if bond_color:
            bond_text_colored = f'{bond_color}{bond_text}{self.COLOR_RESET}'
        else:
            bond_text_colored = bond_text

        if bond.company_portfolio_percent:
            company_text = f'({bond.company_portfolio_percent})'
            company_color = ''

            val = Decimal(bond.company_portfolio_percent.replace('%', '').replace(' ', ''))
            if val > 5.0:
                company_color = self.COLOR_RED

            if company_color:
                company_text_colored = f'{company_color}{company_text}{self.COLOR_RESET}'
            else:
                company_text_colored = company_text

            combined_text = f'{bond_text_colored} {company_text_colored}'
        else:
            combined_text = bond_text_colored

        clean_len = len(bond.portfolio_percent)
        if bond.company_portfolio_percent:
            clean_len += len(bond.company_portfolio_percent) + 3

        padding = ' ' * max(0, self.PORTFOLIO_WIDTH - clean_len)

        return f'{combined_text}{padding}'

    def _format_coupon_yield(self, bond: BondInfo, portfolio_yield: Decimal) -> str:
        """Раскрасить купонную доходность в сравнении с общей по портфелю."""
        current_yield_text = f'{bond.coupon_yield_before_tax} / {bond.coupon_yield_after_tax}'
        color = ''

        bond_yield_str = bond.coupon_yield_before_tax.split('%')[0].strip()
        bond_yield_val = Decimal(bond_yield_str)

        if bond_yield_val > portfolio_yield:
            color = self.COLOR_GREEN
        elif bond_yield_val < portfolio_yield:
            color = self.COLOR_RED

        return self._colorize(current_yield_text, color, self.CURRENT_YIELD_WIDTH)

    def print_portfolio_info(self, portfolio_info: BondPortfolioInfo) -> None:
        """
        Вывести сводную информацию по облигационному портфелю.

        :param portfolio_info: сводная информация по портфелю
        """
        difference = portfolio_info.current_value - portfolio_info.total_invested
        difference_sign = '+' if difference >= 0 else '-'
        difference_str = f'{difference_sign}{self._format_decimal_ru(abs(difference))} ₽'

        change_color = ''
        if portfolio_info.change_percent > 0:
            change_color = self.COLOR_GREEN
        elif portfolio_info.change_percent < 0:
            change_color = self.COLOR_RED

        change_text = f'({self._format_percent(portfolio_info.change_percent)} | {difference_str})'
        colored_change = f'{change_color}{change_text}{self.COLOR_RESET}' if change_color else change_text

        print(f'Кол-во облигаций: {portfolio_info.total_quantity}')
        print(f'Вложено: {self._format_decimal_ru(portfolio_info.total_invested)} ₽')
        print(
            f'Актуальная цена портфеля: {self._format_decimal_ru(portfolio_info.current_value)} ₽ '
            f'{colored_change}',
        )
        print(
            f'Купонная доходность (до/после): '
            f'{portfolio_info.coupon_yield_before_tax:.2f}% / '
            f'{portfolio_info.coupon_yield_after_tax:.2f}%',
        )
        print(
            f'Годовая прибыль (до/после): '
            f'{self._format_decimal_ru(portfolio_info.annual_income_before_tax)} ₽ / '
            f'{self._format_decimal_ru(portfolio_info.annual_income_after_tax)} ₽',
        )
        print(
            f'Ежемесячная прибыль (до/после): '
            f'{self._format_decimal_ru(portfolio_info.monthly_income_before_tax)} ₽ / '
            f'{self._format_decimal_ru(portfolio_info.monthly_income_after_tax)} ₽',
        )
        print()

    def print_bonds_table(self, bonds: list[BondInfo], portfolio_info: BondPortfolioInfo) -> None:
        """
        Вывести облигации в виде таблицы.

        :param bonds: список облигаций
        :param portfolio_info: сводная информация по портфелю (для сравнения доходностей)
        """
        print(self.BONDS_TABLE_HEADER)
        print('-' * len(self.BONDS_TABLE_HEADER))

        portfolio_yield = portfolio_info.coupon_yield_before_tax

        for index, bond in enumerate(bonds, start=1):
            coupon = f'{bond.next_coupon_before_tax} / {bond.next_coupon_after_tax}'

            maturity = self._format_maturity(bond.maturity_date)
            buy_price = self._format_buy_price(bond.buy_price, bond.nominal)
            portfolio_percent = self._format_portfolio_percent(bond)
            coupon_yield = self._format_coupon_yield(bond, portfolio_yield)

            print(
                f'{index:<{self.INDEX_WIDTH}}'
                f'{bond.name:<{self.NAME_WIDTH}.{self.NAME_WIDTH}}'
                f'{bond.rating:<{self.RATING_WIDTH}}'
                f'{maturity}'
                f'{bond.nominal:<{self.NOMINAL_WIDTH}}'
                f'{bond.amortization:<{self.AMORTIZATION_WIDTH}}'
                f'{bond.floater:<{self.FLOATER_WIDTH}}'
                f'{buy_price}'
                f'{bond.quantity:<{self.QUANTITY_WIDTH}}'
                f'{bond.coupons_per_year:<{self.COUPONS_WIDTH}}'
                f'{coupon:<{self.COUPON_WIDTH}}'
                f'{portfolio_percent}'
                f'{coupon_yield}'
                f'{bond.yield_to_maturity:<{self.YTM_WIDTH}}',
            )
        print()
