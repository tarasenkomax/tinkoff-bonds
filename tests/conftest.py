from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from bonds.adapter import TinkoffInvestAdapter


@pytest.fixture
def available_accounts(request) -> list[str]:
    """
    Список доступных счетов.

    По умолчанию — `['acc-1', 'acc-2']`. Тесты могут переопределить
    значение через `@pytest.mark.parametrize(..., indirect=True)`.
    """
    return getattr(request, 'param', ['acc-1', 'acc-2'])


@pytest.fixture
def mock_client(available_accounts: list[str]) -> MagicMock:
    """Мок SDK-клиента с настраиваемым списком доступных счетов."""
    client = MagicMock()
    client.users.get_accounts.return_value = MagicMock(
        accounts=[MagicMock(id=acc_id) for acc_id in available_accounts],
    )
    return client


@pytest.fixture
def make_adapter(mock_client: MagicMock):
    """Фабрика адаптеров для тестов."""
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
    """Фабрика купонов со сдвигом даты от «сейчас».

    :param days: сдвиг в днях (может быть отрицательным)
    """
    def _make(days: int) -> MagicMock:
        coupon = MagicMock()
        coupon.coupon_date = datetime.now(timezone.utc) + timedelta(days=days)
        coupon.pay_one_bond = MagicMock(units=10, nano=0)
        return coupon

    return _make
