import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from t_tech.invest import OperationState, OperationType

from bonds.schemas import CouponDay, CouponMonth, CouponPayment
from bonds.service import BondService


class TestAggregatePositions:
    """Тесты агрегации позиций одной облигации со всех счетов."""
    def test_empty_positions_returns_empty(self, make_adapter_mock) -> None:
        """Пустой список позиций даёт пустой результат."""
        service = BondService(make_adapter_mock())

        assert service._aggregate_positions([]) == []

    def test_single_position_preserved(
        self,
        make_adapter_mock,
        make_position,
    ) -> None:
        """Одна позиция превращается в одну агрегированную с теми же значениями."""
        service = BondService(make_adapter_mock())
        position = make_position(
            average_price_units=900,
            current_price_units=950,
        )

        result = service._aggregate_positions([position])

        assert len(result) == 1
        agg = result[0]
        assert agg.figi == position.figi
        assert agg.quantity == position.quantity.units
        assert agg.average_position_price == Decimal('900')
        assert agg.current_price == Decimal('950')

    def test_quantity_sums_across_accounts(
        self,
        make_adapter_mock,
        make_position,
        make_figi,
    ) -> None:
        """Количество облигаций складывается при агрегации по FIGI."""
        service = BondService(make_adapter_mock())
        figi = make_figi()
        positions = [
            make_position(figi=figi, quantity_units=10),
            make_position(figi=figi, quantity_units=5),
        ]

        result = service._aggregate_positions(positions)

        assert len(result) == 1
        assert result[0].quantity == 15

    def test_weighted_average_price(
        self,
        make_adapter_mock,
        make_position,
        make_figi,
    ) -> None:
        """Цена покупки считается средневзвешенной по количеству."""
        service = BondService(make_adapter_mock())
        figi = make_figi()
        positions = [
            make_position(figi=figi, quantity_units=10, average_price_units=800),
            make_position(figi=figi, quantity_units=30, average_price_units=1000),
        ]

        result = service._aggregate_positions(positions)

        # (10*800 + 30*1000) / 40 = 950
        assert result[0].average_position_price == Decimal('950')

    def test_different_figi_separate(
        self,
        make_adapter_mock,
        make_position,
        make_figi,
    ) -> None:
        """Позиции с разными FIGI агрегируются независимо."""
        service = BondService(make_adapter_mock())
        figi_1 = make_figi()
        figi_2 = make_figi()
        positions = [
            make_position(figi=figi_1, quantity_units=10),
            make_position(figi=figi_2, quantity_units=20),
        ]

        result = service._aggregate_positions(positions)

        assert len(result) == 2
        by_figi = {agg.figi: agg for agg in result}
        assert by_figi[figi_1].quantity == 10
        assert by_figi[figi_2].quantity == 20


class TestCalculatePositionPercent:
    """Тесты расчёта доли облигации в портфеле."""
    def test_normal_case(self, make_aggregated_position) -> None:
        """Доля считается как отношение количества к общему количеству в процентах."""
        position = make_aggregated_position(quantity=25)

        result = BondService._calculate_position_percent(position, total_bonds_quantity=100)

        assert result == Decimal('25')
        assert BondService._calculate_position_percent(position, 0) == Decimal(0)


class TestCalculateYieldToMaturity:
    """Тесты расчёта приблизительной доходности к погашению (YTM)."""
    @pytest.fixture
    def fixed_now(self) -> datetime:
        """Фиксированный момент времени для воспроизводимых расчётов."""
        return datetime(2025, 1, 1, tzinfo=timezone.utc)

    def test_normal_case(
        self,
        make_adapter_mock,
        make_bond,
        make_aggregated_position,
        fixed_now,
    ) -> None:
        """
        Проверяет формулу YTM:

            (годовой купон + (номинал − цена) / лет) / цена * 100
        """
        # 1 год до погашения, номинал 1000, цена 900, годовой купон 100
        bond = make_bond(
            maturity_date=fixed_now + timedelta(days=365),
            nominal_units=1000,
            coupon_quantity_per_year=2,
        )
        position = make_aggregated_position(average_position_price=Decimal('900'))
        service = BondService(make_adapter_mock())

        # годовой купон = 50 * 2 = 100
        # redemption_gain = (1000 - 900) / 1 = 100
        # ytm = (100 + 100) / 900 * 100 ≈ 22.22
        result = service._calculate_yield_to_maturity(
            bond=bond,
            position=position,
            coupon=Decimal('50'),
            now=fixed_now,
        )

        assert result == pytest.approx(Decimal('22.2222'), rel=Decimal('0.001'))

    def test_no_maturity_date_returns_zero(
        self,
        make_adapter_mock,
        make_bond,
        make_aggregated_position,
    ) -> None:
        """Без даты погашения YTM не рассчитывается и равен нулю."""
        bond = make_bond(maturity_date=None)
        bond.maturity_date = None
        position = make_aggregated_position()
        service = BondService(make_adapter_mock())

        result = service._calculate_yield_to_maturity(bond, position, Decimal('50'))

        assert result == Decimal(0)


class TestCalculateCouponYield:
    """Тесты расчёта текущей купонной доходности (до и после НДФЛ)."""
    def test_before_tax_normal(
        self,
        make_adapter_mock,
        make_bond,
        make_aggregated_position,
    ) -> None:
        """Купонная доходность = годовой купон / цена покупки * 100."""
        bond = make_bond(coupon_quantity_per_year=2)
        position = make_aggregated_position(average_position_price=Decimal('1000'))
        service = BondService(make_adapter_mock())

        # (50 * 2) / 1000 * 100 = 10%
        result = service._calculate_coupon_yield_before_tax(bond, position, Decimal('50'))

        assert result == Decimal('10')


class TestCalculateCouponAfterTax:
    """Тесты расчёта купона после удержания НДФЛ."""
    def test_13_percent(self, make_adapter_mock) -> None:
        """Купон уменьшается на 13% НДФЛ."""
        service = BondService(make_adapter_mock())

        result = service._calculate_coupon_after_tax(Decimal('100'))

        # 100 * (1 - 0.13) = 87
        assert result == Decimal('87')


class TestCalculatePortfolioChangePercent:
    """Тесты расчёта изменения стоимости портфеля в процентах."""
    def test_growth(self) -> None:
        """Рост стоимости даёт положительное значение."""
        result = BondService._calculate_portfolio_change_percent(
            invested=Decimal('1000'),
            current_value=Decimal('1100'),
        )

        assert result == Decimal('10')

    def test_loss(self) -> None:
        """Падение стоимости даёт отрицательное значение."""
        result = BondService._calculate_portfolio_change_percent(
            invested=Decimal('1000'),
            current_value=Decimal('900'),
        )

        assert result == Decimal('-10')


class TestCollectBondMetrics:
    """Тесты сбора метрик по всем облигациям портфеля."""
    def test_empty_portfolio_returns_empty(self, make_adapter_mock) -> None:
        """Пустой портфель даёт пустой список метрик."""
        service = BondService(make_adapter_mock(portfolios=[]))

        assert service._collect_bond_metrics() == []

    def test_skips_position_when_bond_is_none(
        self,
        make_adapter_mock,
        make_portfolio,
        make_position,
    ) -> None:
        """Если SDK не вернул облигацию по FIGI, позиция пропускается."""
        position = make_position()
        portfolio = make_portfolio(position)
        adapter = make_adapter_mock(
            portfolios=[portfolio],
            bonds_by_figi={position.figi: None},
        )
        service = BondService(adapter)

        assert service._collect_bond_metrics() == []

    def test_collects_metrics_for_valid_position(
        self,
        make_adapter_mock,
        make_portfolio,
        make_position,
        make_bond,
        make_coupon,
    ) -> None:
        """Для корректной позиции собираются все метрики — купон, YTM, доходности."""
        position = make_position(
            quantity_units=10,
            average_price_units=900,
        )
        portfolio = make_portfolio(position)
        bond = make_bond(coupon_quantity_per_year=2)
        coupon = make_coupon(pay_one_bond_units=30)

        adapter = make_adapter_mock(
            portfolios=[portfolio],
            bonds_by_figi={position.figi: bond},
            next_coupons_by_figi={position.figi: coupon},
        )
        service = BondService(adapter)

        metrics = service._collect_bond_metrics()

        assert len(metrics) == 1
        metric = metrics[0]
        assert metric.bond is bond
        assert metric.position.figi == position.figi
        assert metric.next_coupon == Decimal('30')
        assert metric.annual_coupon_before_tax == Decimal('60')  # 30 * 2
        assert metric.annual_coupon_after_tax == Decimal('52.2')  # 30*0.87 * 2


class TestGetBonds:
    """Тесты публичного метода получения списка облигаций."""
    def test_empty_portfolio_returns_empty(self, make_adapter_mock) -> None:
        """Пустой портфель — пустой список."""
        service = BondService(make_adapter_mock(portfolios=[]))

        assert service._get_bonds() == []

    def test_sorted_by_name_case_insensitive(
        self,
        make_adapter_mock,
        make_portfolio,
        make_position,
        make_bond,
    ) -> None:
        """Сортировка по имени регистронезависимая."""
        positions = [
            make_position(figi='FIGI-B', quantity_units=1),
            make_position(figi='FIGI-A', quantity_units=1),
        ]
        portfolio = make_portfolio(*positions)

        bonds = {
            'FIGI-A': make_bond(name='АВТОБАН-Финанс БО-П08'),
            'FIGI-B': make_bond(name='Балтийский лизинг БО-П11'),
        }
        adapter = make_adapter_mock(
            portfolios=[portfolio],
            bonds_by_figi=bonds,
        )
        service = BondService(adapter)

        result = service._get_bonds()

        assert [bond.name for bond in result] == ['АВТОБАН-Финанс БО-П08', 'Балтийский лизинг БО-П11']

    def test_returns_bond_info_for_each_position(
        self,
        make_adapter_mock,
        make_portfolio,
        make_position,
        make_bond,
        make_coupon,
    ) -> None:
        """Для каждой позиции создаётся BondInfo с корректными полями."""
        position = make_position(quantity_units=5)
        portfolio = make_portfolio(position)
        bond = make_bond()
        coupon = make_coupon(pay_one_bond_units=30)

        adapter = make_adapter_mock(
            portfolios=[portfolio],
            bonds_by_figi={position.figi: bond},
            next_coupons_by_figi={position.figi: coupon},
        )
        service = BondService(adapter)

        result = service._get_bonds()

        assert len(result) == 1
        assert result[0].name == bond.name
        assert result[0].quantity == position.quantity.units

    def test_company_percent_assigned(
        self,
        make_adapter_mock,
        make_portfolio,
        make_position,
        make_bond,
        make_coupon,
    ) -> None:
        """Процент компании заполняется, если бумаг несколько."""
        pos1 = make_position(quantity_units=10)
        pos2 = make_position(quantity_units=20)
        portfolio = make_portfolio(pos1, pos2)

        bond1 = make_bond(name='АПРИ БО-002Р-13')
        bond2 = make_bond(name='АПРИ БО-002Р-14')
        coupon = make_coupon()

        adapter = make_adapter_mock(
            portfolios=[portfolio],
            bonds_by_figi={
                pos1.figi: bond1,
                pos2.figi: bond2
            },
            next_coupons_by_figi={
                pos1.figi: coupon,
                pos2.figi: coupon
            },
        )
        service = BondService(adapter)

        bonds = service._get_bonds()

        # Общее количество = 30. Доля компании = 30/30 = 100%
        assert bonds[0].company_portfolio_percent == '100.00%'
        assert bonds[1].company_portfolio_percent == '100.00%'


class TestGetPortfolioInfo:
    """Тесты публичного метода получения сводной информации по портфелю."""
    def test_empty_portfolio_returns_zeros(self, make_adapter_mock) -> None:
        """Пустой портфель — все суммы и проценты равны нулю."""
        service = BondService(make_adapter_mock(portfolios=[]))

        info = service._get_portfolio_info()

        assert info.total_quantity == 0
        assert info.total_invested == Decimal(0)
        assert info.current_value == Decimal(0)
        assert info.change_percent == Decimal(0)
        assert info.coupon_yield_before_tax == Decimal(0)
        assert info.annual_income_before_tax == Decimal(0)
        assert info.monthly_income_before_tax == Decimal(0)

    def test_annual_and_monthly_income(
        self,
        make_adapter_mock,
        make_portfolio,
        make_position,
        make_bond,
        make_coupon,
    ) -> None:
        """
        Годовая прибыль = Σ(годовой купон × количество).

        Ежемесячная прибыль = годовая / 12.
        """
        # 10 облигаций, купон 30, выплат 2 в год => годовой 60 × 10 = 600
        position = make_position(quantity_units=10)
        portfolio = make_portfolio(position)
        bond = make_bond(coupon_quantity_per_year=2)
        coupon = make_coupon(pay_one_bond_units=30)

        adapter = make_adapter_mock(
            portfolios=[portfolio],
            bonds_by_figi={position.figi: bond},
            next_coupons_by_figi={position.figi: coupon},
        )
        service = BondService(adapter)

        info = service._get_portfolio_info()

        assert info.annual_income_before_tax == Decimal('600')
        assert info.monthly_income_before_tax == Decimal('50')
        assert info.annual_income_after_tax < info.annual_income_before_tax
        assert info.monthly_income_after_tax == info.annual_income_after_tax / Decimal(12)

    def test_totals(
        self,
        make_adapter_mock,
        make_portfolio,
        make_position,
        make_bond,
        make_coupon,
    ) -> None:
        """Вложено, текущая стоимость и изменение считаются по всем позициям."""
        position = make_position(
            quantity_units=10,
            average_price_units=900,
            current_price_units=950,
        )
        portfolio = make_portfolio(position)
        bond = make_bond()
        coupon = make_coupon()

        adapter = make_adapter_mock(
            portfolios=[portfolio],
            bonds_by_figi={position.figi: bond},
            next_coupons_by_figi={position.figi: coupon},
        )
        service = BondService(adapter)

        info = service._get_portfolio_info()

        assert info.total_quantity == 10
        assert info.total_invested == Decimal('9000')  # 900 * 10
        assert info.current_value == Decimal('9500')  # 950 * 10
        assert info.change_percent == pytest.approx(Decimal('5.55'), rel=Decimal('0.01'))


class TestGetCompanyKey:
    """Тесты определения ключа компании (эмитента)."""
    @pytest.mark.parametrize(
        'name, expected',
        [
            ('АПРИ БО-002Р-13', 'АПРИ'),
            ('ВИС ФИНАНС БО-П10', 'ВИС ФИНАНС'),
            ('АФК Система БО 001Р-30', 'АФК Система'),
            ('АФК Система 002Р-14', 'АФК Система'),
            ('ОФЗ 26254', 'ОФЗ'),
            ('РОЛЬФ БО 001Р-07', 'РОЛЬФ'),
            ('ГТЛК БО 002P-09', 'ГТЛК'),
            ('Тинькофф', 'Тинькофф'),
        ],
    )
    def test_get_company_key(self, name: str, expected: str) -> None:
        """Ключ компании правильно отрезает номер выпуска."""
        assert BondService._get_company_key(name) == expected


class TestCalculateCompanyShares:
    """Тесты расчёта суммарных долей по компаниям."""
    def test_single_bond_no_share(self, make_adapter_mock, make_position, make_bond) -> None:
        """Если у компании одна облигация, общий процент не считается (None)."""
        position = make_position(quantity_units=10)
        metric = MagicMock(
            position=position,
            bond=make_bond(name='Селигдар 001Р-02'),
        )
        service = BondService(make_adapter_mock())

        shares = service._calculate_company_shares([metric], total_bonds_quantity=10)

        # Ключ "Селигдар", значение None (так как бумага одна)
        assert shares['Селигдар'] is None

    def test_multiple_bonds_summed(self, make_adapter_mock, make_bond) -> None:
        """Если у компании несколько бумаг, их количество суммируется."""
        pos1 = MagicMock()
        pos1.quantity = 10

        pos2 = MagicMock()
        pos2.quantity = 15

        metric1 = MagicMock(position=pos1, bond=make_bond(name='РОЛЬФ БО 001Р-07'))
        metric2 = MagicMock(position=pos2, bond=make_bond(name='РОЛЬФ БО 001Р-08'))

        service = BondService(make_adapter_mock())

        shares = service._calculate_company_shares(
            [metric1, metric2],
            total_bonds_quantity=100,
        )

        assert shares['РОЛЬФ'] == '25.00%'


class TestCollectBondMetricsCache:
    """Тесты кеширования метрик."""
    def test_second_call_uses_cache(
        self,
        make_adapter_mock,
        make_portfolio,
        make_position,
        make_bond,
        make_coupon,
    ) -> None:
        """Повторный вызов не должен делать новые запросы к адаптеру."""
        position = make_position()
        portfolio = make_portfolio(position)
        bond = make_bond()
        coupon = make_coupon()

        adapter = make_adapter_mock(
            portfolios=[portfolio],
            bonds_by_figi={position.figi: bond},
            next_coupons_by_figi={position.figi: coupon},
        )
        service = BondService(adapter)

        # Первый вызов
        service._collect_bond_metrics()
        # Второй вызов
        service._collect_bond_metrics()

        adapter.get_portfolios.assert_called_once()
        adapter.get_bond_by_figi.assert_called_once()


class TestGetPortfolioJson:
    """Тесты формирования JSON."""
    def test_valid_json_structure(
        self,
        make_adapter_mock,
        make_portfolio,
        make_position,
        make_bond,
        make_coupon,
    ) -> None:
        """JSON содержит ключи portfolio_info и bonds."""
        position = make_position()
        portfolio = make_portfolio(position)
        bond = make_bond()
        coupon = make_coupon()

        adapter = make_adapter_mock(
            portfolios=[portfolio],
            bonds_by_figi={position.figi: bond},
            next_coupons_by_figi={position.figi: coupon},
        )
        service = BondService(adapter)

        json_str = service.get_portfolio_json()
        data = json.loads(json_str)

        assert 'portfolio_info' in data
        assert 'bonds' in data
        assert isinstance(data['bonds'], list)
        assert len(data['bonds']) == 1

    def test_decimal_converted_to_float(
        self,
        make_adapter_mock,
        make_portfolio,
        make_position,
        make_bond,
        make_coupon,
    ) -> None:
        """Проверяем, что Decimal конвертируется в числа, а не строки."""
        position = make_position()
        portfolio = make_portfolio(position)
        bond = make_bond()
        coupon = make_coupon()

        adapter = make_adapter_mock(
            portfolios=[portfolio],
            bonds_by_figi={position.figi: bond},
            next_coupons_by_figi={position.figi: coupon},
        )
        service = BondService(adapter)

        json_str = service.get_portfolio_json()
        data = json.loads(json_str)

        assert isinstance(data['portfolio_info']['total_invested'], (int, float))
        assert isinstance(data['portfolio_info']['change_percent'], (int, float))


class TestGetCalendarEndDate:
    """Тесты определения конца периода купонного календаря."""
    @pytest.mark.parametrize(
        ('start_date', 'expected'),
        [
            (date(2026, 11, 1), date(2027, 10, 31)),
            (date(2026, 1, 1), date(2026, 12, 31)),
            (date(2024, 3, 1), date(2025, 2, 28)),
            (date(2023, 3, 1), date(2024, 2, 29)),
        ],
    )
    def test_returns_last_day_of_twelfth_month(
        self,
        start_date: date,
        expected: date,
    ) -> None:
        """Проверяет расчёт последнего дня двенадцатого месяца."""
        result = BondService._get_calendar_end_date(start_date)

        assert result == expected


class TestGetCurrentMonthCouponOperations:
    """Тесты получения фактически выплаченных купонов."""
    def test_returns_only_executed_coupon_operations_for_portfolio_bonds(
        self,
        make_adapter_mock,
        make_coupon_metric,
    ) -> None:
        """Проверяет фильтрацию операций по типу, статусу и FIGI."""
        coupon_operation = MagicMock(
            operation_type=OperationType.OPERATION_TYPE_COUPON,
            state=OperationState.OPERATION_STATE_EXECUTED,
            figi='figi-1',
        )
        non_coupon_operation = MagicMock(
            operation_type=OperationType.OPERATION_TYPE_BUY,
            state=OperationState.OPERATION_STATE_EXECUTED,
            figi='figi-1',
        )
        unexecuted_operation = MagicMock(
            operation_type=OperationType.OPERATION_TYPE_COUPON,
            state=OperationState.OPERATION_STATE_PROGRESS,
            figi='figi-1',
        )
        foreign_bond_operation = MagicMock(
            operation_type=OperationType.OPERATION_TYPE_COUPON,
            state=OperationState.OPERATION_STATE_EXECUTED,
            figi='figi-2',
        )

        operations = [
            coupon_operation,
            non_coupon_operation,
            unexecuted_operation,
            foreign_bond_operation,
        ]

        adapter = make_adapter_mock(operations=operations)
        service = BondService(adapter)

        start_date = date(2026, 11, 1)
        now = datetime(2026, 11, 19, 12, 0, tzinfo=BondService.MOSCOW_TZ)
        metrics = [make_coupon_metric()]

        result = service._get_current_month_coupon_operations(
            start_date=start_date,
            now=now,
            metrics=metrics,
        )

        assert result == [coupon_operation]

    def test_requests_operations_for_correct_period(
        self,
        make_adapter_mock,
        make_coupon_metric,
    ) -> None:
        """Проверяет передачу периода в адаптер в UTC."""
        adapter = make_adapter_mock(operations=[])
        service = BondService(adapter)

        start_date = date(2026, 11, 1)
        now = datetime(2026, 11, 19, 12, 0, tzinfo=BondService.MOSCOW_TZ)

        service._get_current_month_coupon_operations(
            start_date=start_date,
            now=now,
            metrics=[make_coupon_metric()],
        )

        adapter.get_all_operations.assert_called_once_with(
            from_date=datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc),
            to_date=datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc),
        )


class TestAggregatePaidCoupons:
    """Тесты группировки фактически выплаченных купонов."""
    def test_aggregates_payments_by_figi(self, make_money) -> None:
        """Проверяет суммирование выплат по каждой облигации."""
        service = BondService(MagicMock())

        operations = [
            MagicMock(figi='figi-1', payment=make_money(units=100)),
            MagicMock(figi='figi-1', payment=make_money(units=50)),
            MagicMock(figi='figi-2', payment=make_money(units=200)),
        ]

        result = service._aggregate_paid_coupons(operations)

        assert result == {
            'figi-1': Decimal('150'),
            'figi-2': Decimal('200'),
        }


class TestGetCouponEvents:
    """Тесты получения купонных событий по облигациям."""
    def test_returns_events_for_each_bond(
        self,
        make_adapter_mock,
        make_coupon_metric,
    ) -> None:
        """Проверяет получение событий для каждой облигации."""
        events_1 = [MagicMock(), MagicMock()]
        events_2 = [MagicMock()]

        adapter = make_adapter_mock(
            coupon_events_by_figi={
                'figi-1': events_1,
                'figi-2': events_2,
            },
        )
        service = BondService(adapter)

        metrics = [
            make_coupon_metric(figi='figi-1'),
            make_coupon_metric(figi='figi-2'),
        ]

        result = service._get_coupon_events(metrics)

        assert result == {
            'figi-1': events_1,
            'figi-2': events_2,
        }


class TestGetCouponLocalDate:
    """Тесты преобразования даты купонного события."""
    @pytest.mark.parametrize(
        ('coupon_date', 'expected'),
        [
            (
                datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc),
                date(2026, 11, 19),
            ),
            (
                datetime(2026, 11, 30, 22, 0, tzinfo=timezone.utc),
                date(2026, 12, 1),
            ),
            (
                datetime(2026, 11, 19, 10, 0),
                date(2026, 11, 19),
            ),
        ],
    )
    def test_converts_coupon_date_to_moscow_date(
        self,
        coupon_date: datetime,
        expected: date,
    ) -> None:
        """Проверяет перевод даты в московский часовой пояс."""
        service = BondService(MagicMock())
        result = service._get_coupon_local_date(coupon_date)

        assert result == expected


class TestBuildMonthDays:
    """Тесты формирования дней с купонными выплатами."""
    def test_sorts_days_by_date(self) -> None:
        """Проверяет сортировку дней по возрастанию даты."""
        service = BondService(MagicMock())

        first_day = date(2026, 11, 5)
        second_day = date(2026, 11, 15)

        result = service._build_month_days(
            month_payments={
                second_day: [],
                first_day: [],
            },
            month_start=date(2026, 11, 1),
            month_end=date(2026, 11, 30),
            today=date(2026, 11, 19),
            is_current_month=False,
        )

        assert [day.date for day in result] == [
            first_day,
            second_day,
        ]

    def test_adds_today_without_payments(self) -> None:
        """Проверяет добавление текущего дня без выплат."""
        service = BondService(MagicMock())
        today = date(2026, 11, 19)

        result = service._build_month_days(
            month_payments={},
            month_start=date(2026, 11, 1),
            month_end=date(2026, 11, 30),
            today=today,
            is_current_month=True,
        )

        assert len(result) == 1
        assert result[0].date == today
        assert result[0].label == '19.11'
        assert result[0].is_today is True
        assert result[0].payments == []

    def test_does_not_add_today_for_another_month(self) -> None:
        """Проверяет, что текущий день не добавляется в другой месяц."""
        service = BondService(MagicMock())

        result = service._build_month_days(
            month_payments={},
            month_start=date(2026, 12, 1),
            month_end=date(2026, 12, 31),
            today=date(2026, 11, 19),
            is_current_month=False,
        )

        assert result == []

    def test_sorts_payments_by_bond_name(self) -> None:
        """Проверяет сортировку выплат по названию облигации."""
        service = BondService(MagicMock())
        payment_date = date(2026, 11, 20)

        payments = [
            CouponPayment(
                bond_name='ТГК-14 001Р-02',
                quantity=1,
                coupon_per_bond=Decimal('10'),
                total_amount=Decimal('10'),
            ),
            CouponPayment(
                bond_name='ОФЗ 26254',
                quantity=1,
                coupon_per_bond=Decimal('10'),
                total_amount=Decimal('10'),
            ),
        ]

        result = service._build_month_days(
            month_payments={payment_date: payments},
            month_start=date(2026, 11, 1),
            month_end=date(2026, 11, 30),
            today=date(2026, 11, 19),
            is_current_month=False,
        )

        assert [payment.bond_name for payment in result[0].payments] == ['ОФЗ 26254', 'ТГК-14 001Р-02']


class TestBuildCouponCalendar:
    """Тесты построения календаря купонных выплат."""
    def test_builds_calendar_for_twelve_months(self) -> None:
        """Проверяет формирование двенадцати месяцев календаря."""
        service = BondService(MagicMock())

        result = service._build_coupon_calendar(
            metrics=[],
            coupon_events={},
            paid_by_figi={},
            start_date=date(2026, 11, 1),
            end_date=date(2027, 10, 31),
            today=date(2026, 11, 19),
        )

        assert len(result) == 12
        assert result[0].name == 'НОЯБРЬ'
        assert result[-1].name == 'ОКТЯБРЬ'

    def test_calculates_coupon_payments_after_tax(self, make_coupon_metric) -> None:
        """Проверяет расчёт купона после НДФЛ и общей суммы выплаты."""
        service = BondService(MagicMock())
        metric = make_coupon_metric()

        coupon_date = datetime(2026, 12, 15, tzinfo=BondService.MOSCOW_TZ)
        event = SimpleNamespace(
            coupon_date=coupon_date,
            pay_one_bond=SimpleNamespace(units=10, nano=0),
        )

        result = service._build_coupon_calendar(
            metrics=[metric],
            coupon_events={'figi-1': [event]},
            paid_by_figi={},
            start_date=date(2026, 11, 1),
            end_date=date(2027, 10, 31),
            today=date(2026, 11, 19),
        )

        december = result[1]

        assert december.year == 2026
        assert december.month == 12
        assert december.total_amount == Decimal('17.40')

        payment = december.days[0].payments[0]

        assert payment.bond_name == 'Тестовая облигация'
        assert payment.quantity == 2
        assert payment.coupon_per_bond == Decimal('8.70')
        assert payment.total_amount == Decimal('17.40')

    def test_uses_last_known_coupon_for_floating_bond(self, make_coupon_metric) -> None:
        """Проверяет использование последнего известного купона флоатера."""
        service = BondService(MagicMock())
        metric = make_coupon_metric(
            quantity=2,
            next_coupon=Decimal('15'),
            floating_coupon_flag=True,
        )

        event = SimpleNamespace(
            coupon_date=datetime(
                2026,
                12,
                15,
                tzinfo=BondService.MOSCOW_TZ,
            ),
            pay_one_bond=SimpleNamespace(units=0, nano=0),
        )

        result = service._build_coupon_calendar(
            metrics=[metric],
            coupon_events={'figi-1': [event]},
            paid_by_figi={},
            start_date=date(2026, 11, 1),
            end_date=date(2027, 10, 31),
            today=date(2026, 11, 19),
        )

        payment = result[1].days[0].payments[0]

        assert payment.coupon_per_bond == Decimal('13.05')
        assert payment.total_amount == Decimal('26.10')

    def test_ignores_events_without_coupon_date(self, make_coupon_metric) -> None:
        """Проверяет пропуск событий без даты купона."""
        service = BondService(MagicMock())
        metric = make_coupon_metric()

        event = SimpleNamespace(
            coupon_date=None,
            pay_one_bond=SimpleNamespace(units=10, nano=0),
        )

        result = service._build_coupon_calendar(
            metrics=[metric],
            coupon_events={'figi-1': [event]},
            paid_by_figi={},
            start_date=date(2026, 11, 1),
            end_date=date(2027, 10, 31),
            today=date(2026, 11, 19),
        )

        assert all(month.total_amount == Decimal('0') for month in result)

    def test_calculates_paid_and_remaining_amount_for_current_month(self, make_coupon_metric) -> None:
        """Проверяет расчёт выплаченной и оставшейся суммы текущего месяца."""
        service = BondService(MagicMock())
        metric = make_coupon_metric()

        event = SimpleNamespace(
            coupon_date=datetime(
                2026,
                11,
                25,
                tzinfo=BondService.MOSCOW_TZ,
            ),
            pay_one_bond=SimpleNamespace(units=10, nano=0),
        )

        result = service._build_coupon_calendar(
            metrics=[metric],
            coupon_events={'figi-1': [event]},
            paid_by_figi={'figi-1': Decimal('5')},
            start_date=date(2026, 11, 1),
            end_date=date(2027, 10, 31),
            today=date(2026, 11, 19),
        )

        current_month = result[0]

        assert current_month.total_amount == Decimal('17.40')
        assert current_month.paid_amount == Decimal('5')
        assert current_month.remaining_amount == Decimal('12.40')

    def test_does_not_include_events_outside_calendar_period(self, make_coupon_metric) -> None:
        """Проверяет исключение купонных событий за пределами календаря."""
        service = BondService(MagicMock())
        metric = make_coupon_metric()

        event = SimpleNamespace(
            coupon_date=datetime(
                2027,
                11,
                15,
                tzinfo=BondService.MOSCOW_TZ,
            ),
            pay_one_bond=SimpleNamespace(units=10, nano=0),
        )

        result = service._build_coupon_calendar(
            metrics=[metric],
            coupon_events={'figi-1': [event]},
            paid_by_figi={},
            start_date=date(2026, 11, 1),
            end_date=date(2027, 10, 31),
            today=date(2026, 11, 19),
        )

        assert all(month.total_amount == Decimal('0') for month in result)


class TestCouponCalendarSerialization:
    """Тесты сериализации DTO купонного календаря."""
    def test_serializes_coupon_payment(self) -> None:
        """Проверяет преобразование купонной выплаты в словарь."""
        payment = CouponPayment(
            bond_name='Тестовая облигация',
            quantity=2,
            coupon_per_bond=Decimal('8.70'),
            total_amount=Decimal('17.40'),
        )

        assert payment.to_dict() == {
            'bond_name': 'Тестовая облигация',
            'quantity': 2,
            'coupon_per_bond': '8.70',
            'total_amount': '17.40',
        }

    def test_serializes_coupon_day(self) -> None:
        """Проверяет преобразование дня с выплатами в словарь."""
        day = CouponDay(
            date=date(2026, 11, 19),
            label='19.11',
            is_today=True,
            payments=[],
        )

        assert day.to_dict() == {
            'date': '2026-11-19',
            'label': '19.11',
            'is_today': True,
            'payments': [],
        }

    def test_serializes_current_month_with_paid_amounts(self) -> None:
        """Проверяет наличие полей фактических выплат у текущего месяца."""
        month = CouponMonth(
            year=2026,
            month=11,
            name='НОЯБРЬ',
            is_current_month=True,
            total_amount=Decimal('100'),
            days=[],
            paid_amount=Decimal('30'),
            remaining_amount=Decimal('70'),
        )

        result = month.to_dict()

        assert result['paid_amount'] == '30'
        assert result['remaining_amount'] == '70'

    def test_does_not_serialize_paid_amounts_for_future_month(self) -> None:
        """Проверяет отсутствие полей фактических выплат у будущего месяца."""
        month = CouponMonth(
            year=2026,
            month=12,
            name='ДЕКАБРЬ',
            is_current_month=False,
            total_amount=Decimal('100'),
            days=[],
        )

        result = month.to_dict()

        assert 'paid_amount' not in result
        assert 'remaining_amount' not in result
