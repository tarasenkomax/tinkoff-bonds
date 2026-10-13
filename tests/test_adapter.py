from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from bonds.adapter import TinkoffInvestAdapter
from bonds.exceptions import InvestAccountAccessError
from freezegun import freeze_time
from t_tech.invest import InstrumentIdType


class TestValidateAccounts:
    """Тесты валидации брокерских счетов при создании адаптера."""
    def test_all_accounts_available_creates_adapter(self, mock_client, make_adapter) -> None:
        adapter = make_adapter(['acc-1', 'acc-2'])

        assert isinstance(adapter, TinkoffInvestAdapter)
        assert adapter._account_ids == ['acc-1', 'acc-2']

    def test_single_available_account_creates_adapter(self, mock_client, make_adapter) -> None:
        adapter = make_adapter(['acc-1'])

        assert adapter._account_ids == ['acc-1']

    def test_one_unavailable_account_raises(self, mock_client, make_adapter) -> None:
        with pytest.raises(InvestAccountAccessError) as exc_info:
            make_adapter(['acc-1', 'unknown-acc'])

        message = str(exc_info.value)
        assert 'unknown-acc' in message
        assert 'acc-1' not in message

    def test_multiple_unavailable_accounts_sorted_in_message(
        self,
        mock_client,
        make_adapter,
    ) -> None:
        """Несколько недоступных — все перечислены и отсортированы."""
        with pytest.raises(InvestAccountAccessError) as exc_info:
            make_adapter(['acc-1', 'unknown-acc-3', 'unknown-acc-1', 'unknown-acc-2'])

        message = str(exc_info.value)

        # Извлекаем список счетов из сообщения после двоеточия
        listed_ids = [acc.strip() for acc in message.split(': ', 1)[1].split(',')]

        assert listed_ids == ['unknown-acc-1', 'unknown-acc-2', 'unknown-acc-3']
        assert 'acc-1' not in listed_ids

    def test_empty_account_ids_creates_adapter(self, mock_client, make_adapter) -> None:
        adapter = make_adapter([])

        assert adapter._account_ids == []

    def test_available_account_of_another_user_raises(self, mock_client, make_adapter) -> None:
        mock_client.users.get_accounts.return_value = MagicMock(
            accounts=[MagicMock(id='my-acc-1')],
        )

        with pytest.raises(InvestAccountAccessError) as exc_info:
            make_adapter(['my-acc-1', 'other-user-acc'])

        assert 'other-user-acc' in str(exc_info.value)

    def test_all_unavailable_accounts_raises(self, mock_client, make_adapter) -> None:
        mock_client.users.get_accounts.return_value = MagicMock(
            accounts=[MagicMock(id='acc-1'), MagicMock(id='acc-2')],
        )

        with pytest.raises(InvestAccountAccessError) as exc_info:
            make_adapter(['foo', 'bar'])

        message = str(exc_info.value)
        assert 'bar' in message
        assert 'foo' in message
        assert 'acc-1' not in message
        assert 'acc-2' not in message


class TestGetPortfolios:
    """Тесты параллельного получения портфелей."""
    def test_empty_accounts_returns_empty_list(self, mock_client, make_adapter) -> None:
        adapter = make_adapter([])

        result = adapter.get_portfolios()

        assert result == []
        mock_client.operations.get_portfolio.assert_not_called()

    def test_single_account_returns_single_portfolio(self, mock_client, make_adapter) -> None:
        portfolio = MagicMock(name='portfolio-1')
        mock_client.operations.get_portfolio.return_value = portfolio

        adapter = make_adapter(['acc-1'])
        result = adapter.get_portfolios()

        assert result == [portfolio]
        mock_client.operations.get_portfolio.assert_called_once_with(account_id='acc-1')

    @pytest.mark.parametrize(
        'available_accounts',
        [['acc-1', 'acc-2', 'acc-3']],
        indirect=True,
    )
    def test_multiple_accounts_preserve_order(self, mock_client, make_adapter) -> None:
        def fake_get_portfolio(account_id: str) -> MagicMock:
            return MagicMock(name=f'portfolio-{account_id}')

        mock_client.operations.get_portfolio.side_effect = fake_get_portfolio

        adapter = make_adapter(['acc-1', 'acc-2', 'acc-3'])
        result = adapter.get_portfolios()

        assert [p._mock_name for p in result] == [
            'portfolio-acc-1',
            'portfolio-acc-2',
            'portfolio-acc-3',
        ]
        assert mock_client.operations.get_portfolio.call_count == 3

    def test_error_in_one_account_propagates(self, mock_client, make_adapter) -> None:
        def fake_get_portfolio(account_id: str) -> MagicMock:
            if account_id == 'acc-2':
                raise RuntimeError('boom')
            return MagicMock(name=f'portfolio-{account_id}')

        mock_client.operations.get_portfolio.side_effect = fake_get_portfolio

        adapter = make_adapter(['acc-1', 'acc-2'])

        with pytest.raises(RuntimeError, match='boom'):
            adapter.get_portfolios()

    @pytest.mark.parametrize(
        'available_accounts',
        [['acc-1', 'acc-2', 'acc-3', 'acc-4', 'acc-5']],
        indirect=True,
    )
    def test_max_workers_limits_pool_but_processes_all(
        self,
        available_accounts,
        mock_client,
        make_adapter,
    ) -> None:
        """max_workers меньше N — все N запросов выполняются."""
        mock_client.operations.get_portfolio.side_effect = lambda account_id: MagicMock(
            name=f'portfolio-{account_id}',
        )

        adapter = make_adapter(available_accounts, max_workers=2)
        result = adapter.get_portfolios()

        assert len(result) == 5
        assert mock_client.operations.get_portfolio.call_count == 5


class TestGetBondByFigi:
    """Тесты получения информации об облигации с кешированием."""
    def test_first_call_hits_sdk(self, mock_client, make_adapter) -> None:
        instrument = MagicMock(name='bond')
        mock_client.instruments.bond_by.return_value = MagicMock(instrument=instrument)

        adapter = make_adapter(['acc-1'])
        result = adapter.get_bond_by_figi('FIGI1')

        assert result is instrument
        mock_client.instruments.bond_by.assert_called_once()

    def test_passes_figi_id_type_and_id(self, mock_client, make_adapter) -> None:
        """SDK вызывается с id_type=FIGI и корректным id."""
        mock_client.instruments.bond_by.return_value = MagicMock(instrument=MagicMock())

        adapter = make_adapter(['acc-1'])
        adapter.get_bond_by_figi('FIGI1')

        mock_client.instruments.bond_by.assert_called_once_with(
            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
            id='FIGI1',
        )

    def test_repeated_call_uses_cache(self, mock_client, make_adapter) -> None:
        instrument = MagicMock(name='bond')
        mock_client.instruments.bond_by.return_value = MagicMock(instrument=instrument)

        adapter = make_adapter(['acc-1'], cache_bonds=True)
        first = adapter.get_bond_by_figi('FIGI1')
        second = adapter.get_bond_by_figi('FIGI1')

        assert first is second
        assert mock_client.instruments.bond_by.call_count == 1

    def test_cache_disabled_hits_sdk_each_time(self, mock_client, make_adapter) -> None:
        mock_client.instruments.bond_by.return_value = MagicMock(instrument=MagicMock())

        adapter = make_adapter(['acc-1'], cache_bonds=False)
        adapter.get_bond_by_figi('FIGI1')
        adapter.get_bond_by_figi('FIGI1')

        assert mock_client.instruments.bond_by.call_count == 2

    def test_different_figi_cached_separately(self, mock_client, make_adapter) -> None:
        bond_a = MagicMock(name='bond-a')
        bond_b = MagicMock(name='bond-b')

        mock_client.instruments.bond_by.side_effect = [
            MagicMock(instrument=bond_a),
            MagicMock(instrument=bond_b),
        ]

        adapter = make_adapter(['acc-1'])
        assert adapter.get_bond_by_figi('FIGI-A') is bond_a
        assert adapter.get_bond_by_figi('FIGI-B') is bond_b
        assert adapter.get_bond_by_figi('FIGI-A') is bond_a
        assert adapter.get_bond_by_figi('FIGI-B') is bond_b
        assert mock_client.instruments.bond_by.call_count == 2

    def test_returns_none_when_sdk_returns_none(self, mock_client, make_adapter) -> None:
        """SDK вернул None в instrument — не падаем, возвращаем None."""
        mock_client.instruments.bond_by.return_value = MagicMock(instrument=None)

        adapter = make_adapter(['acc-1'])
        result = adapter.get_bond_by_figi('FIGI1')

        assert result is None


class TestGetBondCoupons:
    """Тесты прямого получения списка купонов облигации."""
    def test_returns_events_from_response(self, mock_client, make_adapter) -> None:
        events = [MagicMock(), MagicMock()]
        mock_client.instruments.get_bond_coupons.return_value = MagicMock(events=events)

        adapter = make_adapter(['acc-1'])
        result = adapter.get_bond_coupons('FIGI1')

        assert result == events

    def test_returns_empty_list_when_no_events(self, mock_client, make_adapter) -> None:
        mock_client.instruments.get_bond_coupons.return_value = MagicMock(events=[])

        adapter = make_adapter(['acc-1'])
        result = adapter.get_bond_coupons('FIGI1')

        assert result == []

    def test_sdk_error_propagates(self, mock_client, make_adapter) -> None:
        mock_client.instruments.get_bond_coupons.side_effect = RuntimeError('network error')

        adapter = make_adapter(['acc-1'])

        with pytest.raises(RuntimeError, match='network error'):
            adapter.get_bond_coupons('FIGI1')


class TestGetNextBondCoupon:
    """Тесты выбора ближайшего купона."""
    def test_returns_closest_coupon(self, mock_client, make_adapter, make_coupon) -> None:
        closest = make_coupon(days=10)
        mock_client.instruments.get_bond_coupons.return_value = MagicMock(
            events=[
                make_coupon(days=30),
                closest,
                make_coupon(days=90),
            ],
        )

        adapter = make_adapter(['acc-1'])
        result = adapter.get_next_bond_coupon('FIGI1')

        assert result is closest

    def test_returns_none_when_all_in_past(self, mock_client, make_adapter, make_coupon) -> None:
        mock_client.instruments.get_bond_coupons.return_value = MagicMock(
            events=[make_coupon(days=-5), make_coupon(days=-100)],
        )

        adapter = make_adapter(['acc-1'])

        assert adapter.get_next_bond_coupon('FIGI1') is None

    def test_returns_none_when_outside_horizon(self, mock_client, make_adapter, make_coupon) -> None:
        mock_client.instruments.get_bond_coupons.return_value = MagicMock(
            events=[make_coupon(days=400)],
        )

        adapter = make_adapter(['acc-1'])

        assert adapter.get_next_bond_coupon('FIGI1') is None

    def test_returns_none_when_events_empty(self, mock_client, make_adapter) -> None:
        mock_client.instruments.get_bond_coupons.return_value = MagicMock(events=[])

        adapter = make_adapter(['acc-1'])

        assert adapter.get_next_bond_coupon('FIGI1') is None

    def test_skips_coupons_with_none_date(self, mock_client, make_adapter, make_coupon) -> None:
        bad = MagicMock(coupon_date=None)
        good = make_coupon(days=20)

        mock_client.instruments.get_bond_coupons.return_value = MagicMock(
            events=[bad, good],
        )

        adapter = make_adapter(['acc-1'])
        result = adapter.get_next_bond_coupon('FIGI1')

        assert result is good

    def test_all_dates_none_returns_none(self, mock_client, make_adapter) -> None:
        """Все купоны без даты — None без TypeError."""
        mock_client.instruments.get_bond_coupons.return_value = MagicMock(
            events=[MagicMock(coupon_date=None), MagicMock(coupon_date=None)],
        )

        adapter = make_adapter(['acc-1'])

        assert adapter.get_next_bond_coupon('FIGI1') is None

    @freeze_time('2025-06-15 12:00:00')
    def test_includes_coupon_right_now(self, mock_client, make_adapter) -> None:
        """Купон ровно «сейчас» включён (now <= coupon_date)."""
        now = datetime.now(timezone.utc)
        coupon = MagicMock()
        coupon.coupon_date = now
        coupon.pay_one_bond = MagicMock()

        mock_client.instruments.get_bond_coupons.return_value = MagicMock(events=[coupon])

        adapter = make_adapter(['acc-1'])
        result = adapter.get_next_bond_coupon('FIGI1')

        assert result is coupon

    @freeze_time('2025-06-15 12:00:00')
    def test_includes_coupon_on_horizon_boundary(self, mock_client, make_adapter) -> None:
        """Купон на границе now + 366 дней включён."""
        now = datetime.now(timezone.utc)
        coupon = MagicMock()
        coupon.coupon_date = now + timedelta(days=366)
        coupon.pay_one_bond = MagicMock()

        mock_client.instruments.get_bond_coupons.return_value = MagicMock(events=[coupon])

        adapter = make_adapter(['acc-1'])
        result = adapter.get_next_bond_coupon('FIGI1')

        assert result is coupon

    @freeze_time('2024-02-29 12:00:00')
    def test_leap_year_boundary(self, mock_client, make_adapter) -> None:
        """
        29 февраля — timedelta(days=366) не падает и не «съезжает».

        Проверяем, что для now=29.02.2024 граница now + 366 дней =
        29.02.2025 включительно.
        """
        now = datetime.now(timezone.utc)
        coupon_at_boundary = MagicMock()
        coupon_at_boundary.coupon_date = now + timedelta(days=366)
        coupon_at_boundary.pay_one_bond = MagicMock()

        coupon_beyond = MagicMock()
        coupon_beyond.coupon_date = now + timedelta(days=367)
        coupon_beyond.pay_one_bond = MagicMock()

        mock_client.instruments.get_bond_coupons.return_value = MagicMock(
            events=[coupon_beyond, coupon_at_boundary],
        )

        adapter = make_adapter(['acc-1'])
        result = adapter.get_next_bond_coupon('FIGI1')

        assert result is coupon_at_boundary
