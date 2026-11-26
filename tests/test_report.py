import json
import os
from datetime import date
from decimal import Decimal

import pytest
from freezegun import freeze_time

from bonds.report import BondReport
from tests.conftest import fake


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
        report._print_portfolio_info(portfolio)

        captured = capsys.readouterr()

        assert BondReport.COLOR_GREEN in captured.out
        assert '+5.00%' in captured.out

    def test_red_when_loss(self, capsys, make_portfolio_info) -> None:
        """Если изменение отрицательное, оно выводится красным."""
        portfolio = make_portfolio_info(change_percent=Decimal('-2.10'))

        report = BondReport()
        report._print_portfolio_info(portfolio)

        captured = capsys.readouterr()

        assert BondReport.COLOR_RED in captured.out
        assert '-2.10%' in captured.out


class TestPrintFromJson:
    """Тесты парсинга JSON и вывода отчета."""
    def test_parses_and_calls_print_methods(self, make_report, portfolio_json_str, capsys) -> None:
        """Метод должен распарсить JSON и вызвать методы вывода."""
        report = make_report
        report.print_portfolio_info_from_json(portfolio_json_str)

        captured = capsys.readouterr()

        assert 'Кол-во облигаций: 10' in captured.out
        assert 'ОФЗ 26254' in captured.out


class TestParseMethods:
    """Тесты восстановления DTO из словарей."""
    def test_parse_portfolio_info_restores_decimals(self, make_report) -> None:
        """Проверяем, что Decimal восстанавливается из float с точностью."""

        invested_val = round(fake.pyfloat(min_value=1000, max_value=1000000), 2)

        data = {
            'total_quantity': fake.random_int(min=1, max=100),
            'total_invested': invested_val,
            'current_value': invested_val * 1.1,
            'change_percent': fake.pyfloat(min_value=-50, max_value=50, right_digits=2),
            'coupon_yield_before_tax': fake.pyfloat(min_value=0, max_value=30, right_digits=2),
            'coupon_yield_after_tax': fake.pyfloat(min_value=0, max_value=30, right_digits=2),
            'yield_to_maturity_before_tax': fake.pyfloat(min_value=0, max_value=30, right_digits=2),
            'yield_to_maturity_after_tax': fake.pyfloat(min_value=0, max_value=30, right_digits=2),
            'annual_income_before_tax': fake.pyfloat(min_value=1000, max_value=100000, right_digits=2),
            'annual_income_after_tax': fake.pyfloat(min_value=1000, max_value=100000, right_digits=2),
            'monthly_income_before_tax': fake.pyfloat(min_value=100, max_value=10000, right_digits=2),
            'monthly_income_after_tax': fake.pyfloat(min_value=100, max_value=10000, right_digits=2),
        }

        result = make_report._parse_portfolio_info(data)

        assert isinstance(result.total_invested, Decimal)
        assert isinstance(result.change_percent, Decimal)
        assert isinstance(result.annual_income_before_tax, Decimal)

        assert result.total_invested == Decimal(str(invested_val))


class TestSaveToFile:
    """Тесты сохранения JSON в файл."""
    def test_saves_file_and_returns_path(self, make_report, tmp_path) -> None:
        """Проверяем, что файл создается и путь возвращается корректно."""
        json_str = '{"test": 123}'
        directory = tmp_path / 'json_dumps'

        filepath = make_report.save_to_file(json_str, directory=str(directory))

        assert os.path.exists(filepath)
        assert 'portfolio_' in filepath
        assert filepath.endswith('.json')

        with open(filepath, 'r', encoding='utf-8') as f:
            assert f.read() == json_str


class TestPrintCouponCalendarFromJson:
    """Тесты вывода купонного календаря."""
    def test_prints_months_days_and_payments(
        self,
        make_report,
        coupon_calendar_json_str,
        capsys,
    ) -> None:
        """Проверяет вывод месяцев, дат и выплат по облигациям."""
        make_report.print_coupon_calendar_from_json(coupon_calendar_json_str)

        output = capsys.readouterr().out

        assert 'НОЯБРЬ 2026' in output
        assert '19.11 (СЕГОДНЯ)' in output
        assert 'Легенда БО 002P-07' in output
        assert 'Селигдар 001Р-02' in output
        assert '37 x 13.59 ₽ = 502.83 ₽' in output
        assert '22 x 17.17 ₽ = 377.74 ₽' in output


class TestPrintCouponMonthsFromJson:
    """Тесты вывода сводки по месяцам."""
    def test_prints_all_months(
        self,
        make_report,
        coupon_calendar_json_str,
        capsys,
    ) -> None:
        """Проверяет вывод сумм выплат по всем месяцам."""
        make_report.print_coupon_months_from_json(coupon_calendar_json_str)

        output = capsys.readouterr().out

        assert 'НОЯБРЬ 2026' in output
        assert 'ДЕКАБРЬ 2026' in output
        assert '+21 264.19 ₽' in output
        assert '+26 155.56 ₽' in output
        assert 'выплачено: 13 989.92 ₽' in output
        assert 'осталось: 7 274.27 ₽' in output


class TestParseCouponPayment:
    """Тесты парсинга выплаты по облигации."""
    def test_parses_coupon_payment(
        self,
        make_report,
        coupon_calendar_json_str,
    ) -> None:
        """Проверяет преобразование данных выплаты в CouponPayment."""
        data = json.loads(coupon_calendar_json_str)
        payment_data = data['months'][0]['days'][0]['payments'][0]

        result = make_report._parse_coupon_payment(payment_data)

        assert result.bond_name == 'Легенда БО 002P-07'
        assert result.quantity == 37
        assert result.coupon_per_bond == Decimal('13.59')
        assert result.total_amount == Decimal('502.83')


class TestParseCouponDay:
    """Тесты парсинга дня купонного календаря."""
    def test_parses_coupon_day(
        self,
        make_report,
        coupon_calendar_json_str,
    ) -> None:
        """Проверяет преобразование данных дня в CouponDay."""
        data = json.loads(coupon_calendar_json_str)
        day_data = data['months'][0]['days'][0]

        result = make_report._parse_coupon_day(day_data)

        assert result.date == date(2026, 11, 19)
        assert result.label == '19.11'
        assert result.is_today is True
        assert len(result.payments) == 2
        assert result.payments[0].bond_name == 'Легенда БО 002P-07'
        assert result.payments[1].bond_name == 'Селигдар 001Р-02'

    def test_parses_day_without_payments(
        self,
        make_report,
        coupon_calendar_json_str,
    ) -> None:
        """Проверяет парсинг дня без выплат."""
        data = json.loads(coupon_calendar_json_str)
        day_data = data['months'][0]['days'][1]

        result = make_report._parse_coupon_day(day_data)

        assert result.date == date(2026, 11, 25)
        assert result.payments == []


class TestParseCouponMonth:
    """Тесты парсинга месяца купонного календаря."""
    def test_parses_coupon_month(
        self,
        make_report,
        coupon_calendar_json_str,
    ) -> None:
        """Проверяет преобразование данных месяца в CouponMonth."""
        data = json.loads(coupon_calendar_json_str)
        month_data = data['months'][0]

        result = make_report._parse_coupon_month(month_data)

        assert result.year == 2026
        assert result.month == 11
        assert result.name == 'НОЯБРЬ'
        assert result.is_current_month is True
        assert result.total_amount == Decimal('21264.19')
        assert result.paid_amount == Decimal('13989.92')
        assert result.remaining_amount == Decimal('7274.27')
        assert len(result.days) == 2

    def test_parses_coupon_month_without_days(
        self,
        make_report,
        coupon_calendar_json_str,
    ) -> None:
        """Проверяет парсинг месяца без обработки дней."""
        data = json.loads(coupon_calendar_json_str)
        month_data = data['months'][0]

        result = make_report._parse_coupon_month(
            month_data,
            include_days=False,
        )

        assert result.year == 2026
        assert result.month == 11
        assert result.total_amount == Decimal('21264.19')
        assert result.days == []

    def test_parses_month_without_payment_summary(
        self,
        make_report,
        coupon_calendar_json_str,
    ) -> None:
        """Проверяет парсинг месяца без сумм выплаченного и оставшегося."""
        data = json.loads(coupon_calendar_json_str)
        month_data = data['months'][1]

        result = make_report._parse_coupon_month(month_data)

        assert result.year == 2026
        assert result.month == 12
        assert result.total_amount == Decimal('26155.56')
        assert result.paid_amount is None
        assert result.remaining_amount is None
        assert len(result.days) == 1


class TestPrintCouponMonthSummary:
    """Тесты краткого вывода сводки купонных выплат."""
    @pytest.mark.parametrize(
        ('remaining_amount', 'should_show_remaining'),
        [
            (Decimal('-50.00'), False),
            (Decimal('0.00'), False),
            (Decimal('200.00'), True),
        ],
    )
    def test_prints_remaining_amount_correctly(
        self,
        capsys,
        make_coupon_month,
        remaining_amount: Decimal,
        should_show_remaining: bool,
    ) -> None:
        """Остаток отображается только при положительном значении."""
        month = make_coupon_month(remaining_amount)

        BondReport()._print_coupon_month_summary(month)

        output = capsys.readouterr().out

        assert 'НОЯБРЬ 2026' in output
        assert '+1 000.00 ₽' in output
        assert 'выплачено: 800.00 ₽' in output

        if should_show_remaining:
            assert 'осталось: 200.00 ₽' in output
        else:
            assert 'осталось:' not in output


class TestPrintCouponMonth:
    """Тесты подробного вывода купонных выплат за месяц."""
    @pytest.mark.parametrize(
        ('remaining_amount', 'should_show_remaining'),
        [
            (Decimal('-50.00'), False),
            (Decimal('0.00'), False),
            (Decimal('200.00'), True),
        ],
    )
    def test_prints_remaining_amount_correctly(
        self,
        capsys,
        make_coupon_month,
        remaining_amount: Decimal,
        should_show_remaining: bool,
    ) -> None:
        """Остаток отображается только при положительном значении."""
        month = make_coupon_month(remaining_amount)

        BondReport()._print_coupon_month(month)

        output = capsys.readouterr().out

        assert 'НОЯБРЬ 2026' in output
        assert '+1 000.00 ₽' in output
        assert 'выплачено: 800.00 ₽' in output

        if should_show_remaining:
            assert 'осталось: 200.00 ₽' in output
        else:
            assert 'осталось:' not in output
