from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
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

    # def test_zero_quantity_position_skipped(
    #     self,
    #     make_adapter_mock,
    #     make_position,
    #     make_figi,
    # ) -> None:
    #     """Позиция с нулевым количеством не учитывается в агрегаци."""
    #     service = BondService(make_adapter_mock())
    #     figi = make_figi()
    #     positions = [
    #         make_position(figi=figi, quantity_units=0),
    #         make_position(figi=figi, quantity_units=5),
    #     ]
    #
    #     result = service._aggregate_positions(positions)
    #
    #     assert result[0].quantity == 5

    # def test_all_zero_quantity_skipped(
    #     self,
    #     make_adapter_mock,
    #     make_position,
    # ) -> None:
    #     """Если у всех позиций нулевое количество — результат пустой."""
    #     service = BondService(make_adapter_mock())
    #     positions = [make_position(quantity_units=0)]
    #
    #     assert service._aggregate_positions(positions) == []

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

        # def test_zero_total_returns_zero(self, make_aggregated_position) -> None:
        #     """При нулевом общем количестве доля равна нулю (защита от деления на ноль)."""
        #     position = make_aggregated_position(quantity=10)

        assert BondService._calculate_position_percent(position, 0) == Decimal(0)

    # def test_negative_total_returns_zero(self, make_aggregated_position) -> None:
    #     """При отрицательном общем количестве доля равна нулю."""
    #     position = make_aggregated_position(quantity=10)
    #
    #     assert BondService._calculate_position_percent(position, -5) == Decimal(0)


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

    # def test_price_zero_returns_zero(
    #     self,
    #     make_adapter_mock,
    #     make_bond,
    #     make_aggregated_position,
    # ) -> None:
    #     """При нулевой цене покупки YTM равен нулю (защита от деления на ноль)."""
    #     bond = make_bond()
    #     position = make_aggregated_position(average_position_price=Decimal('0'))
    #     service = BondService(make_adapter_mock())
    #
    #     result = service._calculate_yield_to_maturity(bond, position, Decimal('50'))
    #
    #     assert result == Decimal(0)

    # def test_maturity_in_past_returns_zero(
    #     self,
    #     make_adapter_mock,
    #     make_bond,
    #     make_aggregated_position,
    #     fixed_now,
    # ) -> None:
    #     """Если дата погашения в прошлом, YTM равен нулю."""
    #     bond = make_bond(maturity_date=fixed_now - timedelta(days=10))
    #     position = make_aggregated_position()
    #     service = BondService(make_adapter_mock())
    #
    #     result = service._calculate_yield_to_maturity(
    #         bond=bond,
    #         position=position,
    #         coupon=Decimal('50'),
    #         now=fixed_now,
    #     )
    #
    #     assert result == Decimal(0)

    # def test_after_tax_reduces_ytm(
    #     self,
    #     make_adapter_mock,
    #     make_bond,
    #     make_aggregated_position,
    #     fixed_now,
    # ) -> None:
    #     """Доходность после НДФЛ строго меньше доходности до налога."""
    #     bond = make_bond(maturity_date=fixed_now + timedelta(days=365))
    #     position = make_aggregated_position(average_position_price=Decimal('900'))
    #     service = BondService(make_adapter_mock())
    #
    #     before = service._calculate_yield_to_maturity(
    #         bond=bond,
    #         position=position,
    #         coupon=Decimal('50'),
    #         now=fixed_now,
    #     )
    #     after = service._calculate_yield_to_maturity(
    #         bond=bond,
    #         position=position,
    #         coupon=Decimal('50'),
    #         after_tax=True,
    #         now=fixed_now,
    #     )
    #
    #     assert after < before


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

    # def test_before_tax_price_zero_returns_zero(
    #     self,
    #     make_adapter_mock,
    #     make_bond,
    #     make_aggregated_position,
    # ) -> None:
    #     """При нулевой цене покупки купонная доходность равна нулю."""
    #     bond = make_bond()
    #     position = make_aggregated_position(average_position_price=Decimal('0'))
    #     service = BondService(make_adapter_mock())
    #
    #     assert service._calculate_coupon_yield_before_tax(bond, position, Decimal('50')) == Decimal(0)

    # def test_before_tax_coupon_zero_returns_zero(
    #     self,
    #     make_adapter_mock,
    #     make_bond,
    #     make_aggregated_position,
    # ) -> None:
    #     """При нулевом купоне купонная доходность равна нулю."""
    #     bond = make_bond()
    #     position = make_aggregated_position()
    #     service = BondService(make_adapter_mock())
    #
    #     assert service._calculate_coupon_yield_before_tax(bond, position, Decimal('0')) == Decimal(0)

    # def test_after_tax_less_than_before(
    #     self,
    #     make_adapter_mock,
    #     make_bond,
    #     make_aggregated_position,
    # ) -> None:
    #     """Купонная доходность после НДФЛ меньше доходности до налога."""
    #     bond = make_bond(coupon_quantity_per_year=2)
    #     position = make_aggregated_position(average_position_price=Decimal('1000'))
    #     service = BondService(make_adapter_mock())
    #
    #     before = service._calculate_coupon_yield_before_tax(bond, position, Decimal('50'))
    #     after = service._calculate_coupon_yield_after_tax(bond, position, Decimal('50'))
    #
    #     assert after < before


class TestCalculateCouponAfterTax:
    """Тесты расчёта купона после удержания НДФЛ."""
    def test_13_percent(self, make_adapter_mock) -> None:
        """Купон уменьшается на 13% НДФЛ."""
        service = BondService(make_adapter_mock())

        result = service._calculate_coupon_after_tax(Decimal('100'))

        # 100 * (1 - 0.13) = 87
        assert result == Decimal('87')

    # def test_zero_coupon(self, make_adapter_mock) -> None:
    #     """При нулевом купоне результат тоже ноль."""
    #     service = BondService(make_adapter_mock())
    #
    #     assert service._calculate_coupon_after_tax(Decimal('0')) == Decimal('0')


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

    # def test_zero_invested_returns_zero(self) -> None:
    #     """При нулевых вложениях результат равен нулю (защита от деления на ноль)."""
    #     result = BondService._calculate_portfolio_change_percent(
    #         invested=Decimal('0'),
    #         current_value=Decimal('1000'),
    #     )
    #
    #     assert result == Decimal(0)


# class TestFormatHelpers:
#     """Тесты вспомогательных форматтеров."""
#     def test_format_maturity_date_normal(self, make_bond) -> None:
#         """Дата погашения форматируется в ДД.ММ.ГГГГ."""
#         bond = make_bond(maturity_date=datetime(2040, 10, 3, tzinfo=timezone.utc))
#
#         assert BondService._format_maturity_date(bond) == '03.10.2040'

# def test_format_maturity_date_none(self, make_bond) -> None:
#     """Без даты погашения возвращается прочерк."""
#     bond = make_bond()
#     bond.maturity_date = None
#
#     assert BondService._format_maturity_date(bond) == '-'

# def test_format_ytm_without_prefix(self) -> None:
#     """Без префикса YTM выводится как пара значений через слэш."""
#     result = BondService._format_ytm(
#         prefix='',
#         before_tax=Decimal('15.12'),
#         after_tax=Decimal('13.15'),
#     )
#
#     assert result == '15.12% / 13.15%'

# def test_format_ytm_with_prefix(self) -> None:
#     """С префиксом тильды каждое значение YTM получает префикс (для флоатеров)."""
#     result = BondService._format_ytm(
#         prefix='~',
#         before_tax=Decimal('15.12'),
#         after_tax=Decimal('13.15'),
#     )
#
#     assert result == '~15.12% / ~13.15%'

# def test_bool_marker_true(self) -> None:
#     """True превращается в '+'. """
#     assert BondService._bool_marker(True) == '+'
#
# def test_bool_marker_false(self) -> None:
#     """False превращается в '-'. """
#     assert BondService._bool_marker(False) == '-'


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

    # def test_skips_position_with_zero_price(
    #     self,
    #     make_adapter_mock,
    #     make_portfolio,
    #     make_position,
    #     make_bond,
    # ) -> None:
    #     """Позиция с нулевой ценой покупки пропускается (нельзя считать доходность)."""
    #     position = make_position()
    #     position.average_position_price_fifo = MagicMock(units=0, nano=0)
    #     portfolio = make_portfolio(position)
    #     bond = make_bond()
    #
    #     adapter = make_adapter_mock(
    #         portfolios=[portfolio],
    #         bonds_by_figi={position.figi: bond},
    #     )
    #     service = BondService(adapter)
    #
    #     assert service._collect_bond_metrics() == []

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

        assert service.get_bonds() == []

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

        result = service.get_bonds()

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

        result = service.get_bonds()

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

        bonds = service.get_bonds()

        # Общее количество = 30. Доля компании = 30/30 = 100%
        assert bonds[0].company_portfolio_percent == '100.00%'
        assert bonds[1].company_portfolio_percent == '100.00%'


class TestGetPortfolioInfo:
    """Тесты публичного метода получения сводной информации по портфелю."""
    def test_empty_portfolio_returns_zeros(self, make_adapter_mock) -> None:
        """Пустой портфель — все суммы и проценты равны нулю."""
        service = BondService(make_adapter_mock(portfolios=[]))

        info = service.get_portfolio_info()

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

        info = service.get_portfolio_info()

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

        info = service.get_portfolio_info()

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
