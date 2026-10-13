from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from bonds.adapter import TinkoffInvestAdapter


@pytest.fixture
def mock_client() -> MagicMock:
    """
    Мок SDK-клиента.

    По умолчанию ``get_accounts`` отдаёт два доступных счёта:
    ``acc-1`` и ``acc-2``.
    """
    client = MagicMock()
    client.users.get_accounts.return_value = MagicMock(
        accounts=[MagicMock(id='acc-1'), MagicMock(id='acc-2')],
    )
    return client


@pytest.fixture
def make_adapter(mock_client: MagicMock):
    """
    Фабрика адаптеров для тестов.

    Позволяет создавать адаптер с произвольным списком счетов
    и опциями, переиспользуя один и тот же мок-клиент.
    """
    def _make(
        account_ids: list[str],
        *,
        cache_bonds: bool = True,
        max_workers: int = 8,
    ) -> TinkoffInvestAdapter:
        return TinkoffInvestAdapter(
            client=mock_client,
            account_ids=account_ids,
            max_workers=max_workers,
            cache_bonds=cache_bonds,
        )

    return _make


@pytest.fixture
def make_coupon():
    """
    Фабрика купонов со сдвигом даты от «сейчас».

    :param days: сдвиг в днях (может быть отрицательным)
    """
    def _make(days: int) -> MagicMock:
        coupon = MagicMock()
        coupon.coupon_date = datetime.now(timezone.utc) + timedelta(days=days)
        coupon.pay_one_bond = MagicMock(units=10, nano=0)
        return coupon

    return _make
