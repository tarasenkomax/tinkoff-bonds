from decimal import Decimal

from t_tech.invest import Client

from bonds.adapter import TinkoffInvestAdapter
from bonds.service import BondInfo, BondService, BondPortfolioInfo
from conf import TINKOFF_ACCOUNT_ID, TINKOFF_TOKEN

NAME_WIDTH = 32
RATING_WIDTH = 10
MATURITY_WIDTH = 16
NOMINAL_WIDTH = 15
AMORTIZATION_WIDTH = 8
FLOATER_WIDTH = 10
BUY_PRICE_WIDTH = 16
QUANTITY_WIDTH = 8
COUPONS_WIDTH = 16
COUPON_WIDTH = 22
PORTFOLIO_WIDTH = 12
YIELD_WIDTH = 22


def _format_percent(
    value: Decimal,
) -> str:
    """
    Форматирует процент с явным знаком.

    Пример:
        0.12 -> +0.12%
        -3.45 -> -3.45%
    """

    return f"{value:+.2f}%"


def _format_decimal_ru(
    value: Decimal,
) -> str:
    """
    Форматирует Decimal в российский формат.

    Пример:
        1234567.89 -> 1.234.567,89
    """

    return (
        f"{value:,.2f}"
        .replace(",", " ")
        .replace(".", ",")
        .replace(" ", ".")
    )


def print_portfolio_info(
    portfolio_info: BondPortfolioInfo,
) -> None:
    """
    Выводит сводную информацию по облигационному портфелю.
    """

    print(f"{'Кол-во облигаций:'} {portfolio_info.total_quantity}")
    print(f"{'Вложено:'} {_format_decimal_ru(portfolio_info.total_invested)} ₽")
    print(
        f"{'Актуальная цена портфеля:'} {_format_decimal_ru(portfolio_info.current_value)} ₽ "
        f"({_format_percent(portfolio_info.change_percent)})"
    )
    print()


def print_bonds_table(
    bonds: list[BondInfo],
) -> None:
    """
    Выводит облигации в виде таблицы.
    """

    header = (
        f"{'Название':<{NAME_WIDTH}}"
        f"{'Рейтинг':<{RATING_WIDTH}}"
        f"{'Дата погашения':<{MATURITY_WIDTH}}"
        f"{'Номинал':<{NOMINAL_WIDTH}}"
        f"{'Аморт.':<{AMORTIZATION_WIDTH}}"
        f"{'Флоатер':<{FLOATER_WIDTH}}"
        f"{'Цена покупки':<{BUY_PRICE_WIDTH}}"
        f"{'Кол-во':<{QUANTITY_WIDTH}}"
        f"{'Выплат в год':<{COUPONS_WIDTH}}"
        f"{'Купон до НДФЛ':<{COUPON_WIDTH}}"
        f"{'Купон после НДФЛ':<{COUPON_WIDTH}}"
        f"{'% портфеля':<{PORTFOLIO_WIDTH}}"
        # f"{'Доходность к погашению':<{YIELD_WIDTH}}"
    )

    print(header)
    print("-" * len(header))

    for bond in bonds:
        print(
            f"{bond.name:<{NAME_WIDTH}.{NAME_WIDTH}}"
            f"{bond.rating:<{RATING_WIDTH}}"
            f"{bond.maturity_date:<{MATURITY_WIDTH}}"
            f"{bond.nominal:<{NOMINAL_WIDTH}}"
            f"{bond.amortization:<{AMORTIZATION_WIDTH}}"
            f"{bond.floater:<{FLOATER_WIDTH}}"
            f"{bond.buy_price:<{BUY_PRICE_WIDTH}}"
            f"{bond.quantity:<{QUANTITY_WIDTH}}"
            f"{bond.coupons_per_year:<{COUPONS_WIDTH}}"
            f"{bond.next_coupon_before_tax:<{COUPON_WIDTH}}"
            f"{bond.next_coupon_after_tax:<{COUPON_WIDTH}}"
            f"{bond.portfolio_percent:<{PORTFOLIO_WIDTH}}"
            # f"{bond.yield_to_maturity:<{YIELD_WIDTH}}"
        )


def main() -> None:
    """
    Точка входа приложения.
    """

    with Client(TINKOFF_TOKEN) as client:
        adapter = TinkoffInvestAdapter(
            client=client,
            account_id=TINKOFF_ACCOUNT_ID,
        )

        bond_service = BondService(adapter)

        portfolio_info = bond_service.get_portfolio_info()
        bonds = bond_service.get_bonds()

        print_portfolio_info(portfolio_info)
        print_bonds_table(bonds)


if __name__ == "__main__":
    main()
