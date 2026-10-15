from decimal import Decimal

from bonds.adapter import TinkoffInvestAdapter
from bonds.service import BondInfo, BondPortfolioInfo, BondService
from bonds.utils import timed
from conf import TINKOFF_BROKER_ACCOUNT_ID, TINKOFF_IIS_ACCOUNT_ID, TINKOFF_TOKEN
from t_tech.invest import Client


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
PORTFOLIO_WIDTH = 12
CURRENT_YIELD_WIDTH = 29
YTM_WIDTH = 10

BONDS_TABLE_HEADER = (
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


def _format_percent(
    value: Decimal,
) -> str:
    """
    Отформатировать процент с явным знаком.

    :param value: значение в процентах
    :return: строка вида `+0.12%` или `-3.45%`
    """

    return f'{value:+.2f}%'


def _format_decimal_ru(
    value: Decimal,
) -> str:
    """
    Отформатировать `Decimal` в российский формат.

    :param value: числовое значение
    :return: строка вида `1.234.567,89`
    """

    return f'{value:,.2f}'.replace(',', ' ').replace('.', ',').replace(' ', '.')


def print_portfolio_info(
    portfolio_info: BondPortfolioInfo,
) -> None:
    """
    Вывести сводную информацию по облигационному портфелю.
    """
    difference = portfolio_info.current_value - portfolio_info.total_invested
    difference_sign = '+' if difference >= 0 else '-'
    difference_str = f'{difference_sign}{_format_decimal_ru(abs(difference))} ₽'

    print(f'Кол-во облигаций: {portfolio_info.total_quantity}')
    print(f'Вложено: {_format_decimal_ru(portfolio_info.total_invested)} ₽')
    print(
        f'Актуальная цена портфеля: {_format_decimal_ru(portfolio_info.current_value)} ₽ '
        f'({_format_percent(portfolio_info.change_percent)} | {difference_str})',
    )
    print(
        f'Купонная доходность (до/после): '
        f'{portfolio_info.coupon_yield_before_tax:.2f}% / '
        f'{portfolio_info.coupon_yield_after_tax:.2f}%',
    )
    print()


def print_bonds_table(
    bonds: list[BondInfo],
) -> None:
    """
    Вывести облигации в виде таблицы.
    """

    print(BONDS_TABLE_HEADER)
    print('-' * len(BONDS_TABLE_HEADER))

    for bond in bonds:
        coupon = f'{bond.next_coupon_before_tax} / ' f'{bond.next_coupon_after_tax}'

        current_yield = f'{bond.coupon_yield_before_tax} / ' f'{bond.coupon_yield_after_tax}'

        print(
            f'{bond.name:<{NAME_WIDTH}.{NAME_WIDTH}}'
            f'{bond.rating:<{RATING_WIDTH}}'
            f'{bond.maturity_date:<{MATURITY_WIDTH}}'
            f'{bond.nominal:<{NOMINAL_WIDTH}}'
            f'{bond.amortization:<{AMORTIZATION_WIDTH}}'
            f'{bond.floater:<{FLOATER_WIDTH}}'
            f'{bond.buy_price:<{BUY_PRICE_WIDTH}}'
            f'{bond.quantity:<{QUANTITY_WIDTH}}'
            f'{bond.coupons_per_year:<{COUPONS_WIDTH}}'
            f'{coupon:<{COUPON_WIDTH}}'
            f'{bond.portfolio_percent:<{PORTFOLIO_WIDTH}}'
            f'{current_yield:<{CURRENT_YIELD_WIDTH}}'
            f'{bond.yield_to_maturity:<{YTM_WIDTH}}',
        )


@timed
def main() -> None:
    """
    Точка входа приложения.
    """

    with Client(TINKOFF_TOKEN) as client:
        adapter = TinkoffInvestAdapter(
            client=client,
            account_ids=[
                TINKOFF_BROKER_ACCOUNT_ID,
                TINKOFF_IIS_ACCOUNT_ID,
            ],
        )

        bond_service = BondService(adapter)

        portfolio_info = bond_service.get_portfolio_info()
        bonds = bond_service.get_bonds()

        print_portfolio_info(portfolio_info)
        print_bonds_table(bonds)


if __name__ == '__main__':
    main()
