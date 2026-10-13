from unittest.mock import MagicMock

import pytest
from bonds.adapter import TinkoffInvestAdapter
from bonds.exceptions import InvestAccountAccessError


class TestValidateAccounts:
    """Тесты валидации брокерских счетов при создании адаптера."""
    def test_all_accounts_available_creates_adapter(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Все счета доступны — адаптер создаётся, account_ids сохранён."""
        adapter = make_adapter(['acc-1', 'acc-2'])

        assert isinstance(adapter, TinkoffInvestAdapter)
        assert adapter._account_ids == ['acc-1', 'acc-2']

    def test_single_available_account_creates_adapter(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Один доступный счёт — адаптер создаётся без ошибки."""
        adapter = make_adapter(['acc-1'])

        assert adapter._account_ids == ['acc-1']

    def test_one_unavailable_account_raises(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Один недоступный счёт — исключение с его id в сообщении."""
        with pytest.raises(InvestAccountAccessError) as exc_info:
            make_adapter(['acc-1', 'unknown-acc'])

        message = str(exc_info.value)
        assert 'unknown-acc' in message
        assert 'acc-1' not in message

    def test_multiple_unavailable_accounts_sorted_in_message(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Несколько недоступных — все перечислены и отсортированы."""
        with pytest.raises(InvestAccountAccessError) as exc_info:
            make_adapter(['acc-1', 'zzz', 'aaa', 'mmm'])

        message = str(exc_info.value)

        for account_id in ('aaa', 'mmm', 'zzz'):
            assert account_id in message

        assert message.index('aaa') < message.index('mmm') < message.index('zzz')
        assert 'acc-1' not in message

    def test_empty_account_ids_creates_adapter(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Пустой список счетов — адаптер создаётся без ошибки."""
        adapter = make_adapter([])

        assert adapter._account_ids == []

    def test_available_account_of_another_user_raises(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Счёт не из ответа get_accounts — валидация не пропускает."""
        mock_client.users.get_accounts.return_value = MagicMock(
            accounts=[MagicMock(id='my-acc-1')],
        )

        with pytest.raises(InvestAccountAccessError) as exc_info:
            make_adapter(['my-acc-1', 'other-user-acc'])

        assert 'other-user-acc' in str(exc_info.value)

    def test_all_unavailable_accounts_raises(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Все указанные счета недоступны — исключение со всеми id."""
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
    def test_empty_accounts_returns_empty_list(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Пустой список счетов — [] без вызовов SDK."""
        adapter = make_adapter([])

        result = adapter.get_portfolios()

        assert result == []
        mock_client.operations.get_portfolio.assert_not_called()

    def test_single_account_returns_single_portfolio(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Один счёт — ровно один вызов SDK, результат в списке."""
        portfolio = MagicMock(name='portfolio-1')
        mock_client.operations.get_portfolio.return_value = portfolio

        adapter = make_adapter(['acc-1'])
        result = adapter.get_portfolios()

        assert result == [portfolio]
        assert mock_client.operations.get_portfolio.call_count == 1
        mock_client.operations.get_portfolio.assert_called_once_with(account_id='acc-1')

    def test_multiple_accounts_preserve_order(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """N счетов — N вызовов, порядок портфелей соответствует счетам."""
        def fake_get_portfolio(account_id: str) -> MagicMock:
            return MagicMock(name=f'portfolio-{account_id}')

        mock_client.operations.get_portfolio.side_effect = fake_get_portfolio

        adapter = make_adapter(['acc-1', 'acc-2'])
        result = adapter.get_portfolios()

        assert [p._mock_name for p in result] == [
            'portfolio-acc-1',
            'portfolio-acc-2',
        ]
        assert mock_client.operations.get_portfolio.call_count == 2

    def test_error_in_one_account_propagates(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Ошибка SDK в одном счёте — исключение прокидывается наружу."""
        def fake_get_portfolio(account_id: str) -> MagicMock:
            if account_id == 'acc-2':
                raise RuntimeError('boom')
            return MagicMock(name=f'portfolio-{account_id}')

        mock_client.operations.get_portfolio.side_effect = fake_get_portfolio

        adapter = make_adapter(['acc-1', 'acc-2'])

        with pytest.raises(RuntimeError, match='boom'):
            adapter.get_portfolios()


class TestGetBondByFigi:
    """Тесты получения информации об облигации с кешированием."""
    def test_first_call_hits_sdk(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Первый вызов — обращение к SDK, результат возвращён."""
        instrument = MagicMock(name='bond')
        mock_client.instruments.bond_by.return_value = MagicMock(instrument=instrument)

        adapter = make_adapter(['acc-1'])
        result = adapter.get_bond_by_figi('FIGI1')

        assert result is instrument
        mock_client.instruments.bond_by.assert_called_once()

    def test_repeated_call_uses_cache(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Повторный вызов с cache_bonds=True не идёт в SDK."""
        instrument = MagicMock(name='bond')
        mock_client.instruments.bond_by.return_value = MagicMock(instrument=instrument)

        adapter = make_adapter(['acc-1'], cache_bonds=True)
        first = adapter.get_bond_by_figi('FIGI1')
        second = adapter.get_bond_by_figi('FIGI1')

        assert first is second
        assert mock_client.instruments.bond_by.call_count == 1

    def test_cache_disabled_hits_sdk_each_time(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """cache_bonds=False — SDK вызывается при каждом обращении."""
        mock_client.instruments.bond_by.return_value = MagicMock(instrument=MagicMock())

        adapter = make_adapter(['acc-1'], cache_bonds=False)
        adapter.get_bond_by_figi('FIGI1')
        adapter.get_bond_by_figi('FIGI1')

        assert mock_client.instruments.bond_by.call_count == 2

    def test_different_figi_cached_separately(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Разные FIGI кешируются независимо."""
        bond_a = MagicMock(name='bond-a')
        bond_b = MagicMock(name='bond-b')

        mock_client.instruments.bond_by.side_effect = [
            MagicMock(instrument=bond_a),
            MagicMock(instrument=bond_b),
        ]

        adapter = make_adapter(['acc-1'])
        assert adapter.get_bond_by_figi('FIGI-A') is bond_a
        assert adapter.get_bond_by_figi('FIGI-B') is bond_b

        # повторные вызовы — из кеша
        assert adapter.get_bond_by_figi('FIGI-A') is bond_a
        assert adapter.get_bond_by_figi('FIGI-B') is bond_b
        assert mock_client.instruments.bond_by.call_count == 2


class TestGetNextBondCoupon:
    """Тесты выбора ближайшего купона."""
    def test_returns_closest_coupon(
        self,
        mock_client: MagicMock,
        make_adapter,
        make_coupon,
    ) -> None:
        """Из нескольких будущих купонов выбран ближайший."""
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

    def test_returns_none_when_all_in_past(
        self,
        mock_client: MagicMock,
        make_adapter,
        make_coupon,
    ) -> None:
        """Все купоны в прошлом — None."""
        mock_client.instruments.get_bond_coupons.return_value = MagicMock(
            events=[make_coupon(days=-5), make_coupon(days=-100)],
        )

        adapter = make_adapter(['acc-1'])

        assert adapter.get_next_bond_coupon('FIGI1') is None

    def test_returns_none_when_outside_horizon(
        self,
        mock_client: MagicMock,
        make_adapter,
        make_coupon,
    ) -> None:
        """Купон дальше года вперёд — None."""
        mock_client.instruments.get_bond_coupons.return_value = MagicMock(
            events=[make_coupon(days=400)],
        )

        adapter = make_adapter(['acc-1'])

        assert adapter.get_next_bond_coupon('FIGI1') is None

    def test_returns_none_when_events_empty(
        self,
        mock_client: MagicMock,
        make_adapter,
    ) -> None:
        """Пустой список купонов — None."""
        mock_client.instruments.get_bond_coupons.return_value = MagicMock(events=[])

        adapter = make_adapter(['acc-1'])

        assert adapter.get_next_bond_coupon('FIGI1') is None

    def test_skips_coupons_with_none_date(
        self,
        mock_client: MagicMock,
        make_adapter,
        make_coupon,
    ) -> None:
        """Купоны с coupon_date=None пропускаются, не падаем."""
        bad = MagicMock(coupon_date=None)
        good = make_coupon(days=20)

        mock_client.instruments.get_bond_coupons.return_value = MagicMock(
            events=[bad, good],
        )

        adapter = make_adapter(['acc-1'])
        result = adapter.get_next_bond_coupon('FIGI1')

        assert result is good
