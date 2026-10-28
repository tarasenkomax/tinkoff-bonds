from decimal import Decimal

from bonds.report import BondReport
from freezegun import freeze_time


class TestFormatBuyPrice:
    """Тесты раскраски цены покупки."""
    def test_below_nominal_is_green(self, make_report):
        """Цена ниже номинала раскрашивается в зелёный."""
        result = make_report._format_buy_price('900.00 ₽', '1000.00 ₽')

        assert BondReport.COLOR_GREEN in result
        assert '900.00 ₽' in result

    def test_above_nominal_is_red(self, make_report):
        """Цена выше номинала раскрашивается в красный."""
        result = BondReport()._format_buy_price('1100.00 ₽', '1000.00 ₽')

        assert BondReport.COLOR_RED in result


class TestFormatMaturity:
    """Тесты раскраски даты погашения."""
    @freeze_time('2025-05-20')
    def test_current_year_is_light_yellow(self):
        """Если погашение в текущем году — светло-жёлтый цвет."""
        result = BondReport()._format_maturity('10.11.2025')

        assert BondReport.COLOR_LIGHT_YELLOW in result

    @freeze_time('2025-05-20')
    def test_next_year_is_yellow(self):
        """Если погашение в следующем году — тёмно-жёлтый цвет."""
        result = BondReport()._format_maturity('10.11.2026')

        assert BondReport.COLOR_YELLOW in result


class TestFormatPortfolioPercent:
    """Тесты раскраски доли портфеля."""
    def test_bond_above_5_red(self, make_bond_info):
        """Если доля облигации больше 5% — она раскрашивается в красный."""
        bond = make_bond_info(portfolio_percent='7.00%', company_portfolio_percent=None)
        result = BondReport()._format_portfolio_percent(bond)

        assert BondReport.COLOR_RED in result

    def test_company_above_5_red_bond_normal(self, make_bond_info):
        """Если доля компании больше 5%, а облигации — меньше, краснеет только значение в скобках."""
        bond = make_bond_info(portfolio_percent='2.00%', company_portfolio_percent='6.00%')
        result = BondReport()._format_portfolio_percent(bond)

        # Проверяем, что красный применяется только к скобкам
        assert BondReport.COLOR_RED in result
        assert f'{BondReport.COLOR_RED}(6.00%){BondReport.COLOR_RESET}' in result


class TestPrintPortfolioInfo:
    """Тесты вывода сводной информации по портфелю."""
    def test_green_when_profit(self, capsys, make_portfolio_info) -> None:
        """Если изменение стоимости положительное, оно выводится зелёным."""
        portfolio = make_portfolio_info(change_percent=Decimal('5.00'))

        report = BondReport()
        report.print_portfolio_info(portfolio)

        captured = capsys.readouterr()

        assert BondReport.COLOR_GREEN in captured.out
        assert '+5.00%' in captured.out

    def test_red_when_loss(self, capsys, make_portfolio_info) -> None:
        """Если изменение отрицательное, оно выводится красным."""
        portfolio = make_portfolio_info(change_percent=Decimal('-2.10'))

        report = BondReport()
        report.print_portfolio_info(portfolio)

        captured = capsys.readouterr()

        assert BondReport.COLOR_RED in captured.out
        assert '-2.10%' in captured.out
