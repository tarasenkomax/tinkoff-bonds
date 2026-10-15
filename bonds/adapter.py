from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from bonds.exceptions import InvestAccountAccessError
from t_tech.invest import Client, InstrumentIdType


class TinkoffInvestAdapter:
    """
    Адаптер работы с конкретным брокерским счётом.

    Скрывает детали SDK от бизнес-кода.
    """
    def __init__(
        self,
        client: Client,
        account_ids: list[str],
        *,
        max_workers: int = 8,
        cache_bonds: bool = True,
    ) -> None:
        """
        :param client: авторизованный SDK клиент
        :param account_ids: идентификаторы брокерских счетов
        :param max_workers: максимальное количество потоков для параллельных запросов портфелей
        :param cache_bonds: кешировать ли справочные данные об облигациях (bond_by / get_bond_coupons) внутри адаптера
        """

        self._client = client
        self._account_ids = account_ids

        self._max_workers = max_workers
        self._cache_bonds = cache_bonds

        self._bond_cache: dict[str, Any] = {}

        self._validate_accounts()

    def _validate_accounts(self) -> None:
        """
        Проверить доступность всех указанных счетов.

        :raises InvestAccountAccessError: если хотя бы один счёт недоступен
        """

        accounts = self._client.users.get_accounts()
        available_ids = {account.id for account in accounts.accounts}

        unavailable_ids = set(self._account_ids) - available_ids
        if unavailable_ids:
            raise InvestAccountAccessError('Недоступны брокерские счета: '
                                           f"{', '.join(sorted(unavailable_ids))}")

    def get_portfolios(self) -> list[Any]:
        """
        Вернуть портфели по всем брокерским счетам.

        Запросы выполняются параллельно (gRPC-канал SDK потокобезопасен).

        :return: список портфелей в порядке `self._account_ids`
        """

        if not self._account_ids:
            return []

        if len(self._account_ids) == 1:
            return [self._get_portfolio(self._account_ids[0])]

        workers = min(self._max_workers, len(self._account_ids))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self._get_portfolio, self._account_ids))

    def _get_portfolio(self, account_id: str) -> Any:
        """
        Запросить портфель по одному счёту.

        :param account_id: идентификатор брокерского счёта
        :return: портфель из SDK
        """
        return self._client.operations.get_portfolio(account_id=account_id)

    def get_bond_by_figi(self, figi: str) -> Any:
        """
        Получить информацию об облигации по FIGI.

        :param figi: FIGI инструмента
        :return: информация об облигации из SDK
        """

        if self._cache_bonds:
            cached = self._bond_cache.get(figi)
            if cached is not None:
                return cached

        instrument = self._client.instruments.bond_by(
            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
            id=figi,
        ).instrument

        if self._cache_bonds:
            self._bond_cache[figi] = instrument

        return instrument

    def get_bond_coupons(self, figi: str):
        """
        Вернуть список купонов облигации.

        :param figi: FIGI облигации
        :return: список купонных выплат
        """

        response = self._client.instruments.get_bond_coupons(figi=figi)

        return response.events

    def get_next_bond_coupon(self, figi: str) -> Any | None:
        """
        Вернуть ближайший купон по облигации.

        Реализован поверх `get_bond_coupons`, чтобы не делать
        лишний HTTP-запрос при повторных вызовах.

        :param figi: FIGI облигации
        :return: ближайшая купонная выплата или `None`, если её нет
        """

        now = datetime.now(timezone.utc)

        upcoming = [
            coupon for coupon in self.get_bond_coupons(figi)
            if coupon.coupon_date is not None and now <= coupon.coupon_date <= now + timedelta(days=366)
        ]

        if not upcoming:
            return None

        return min(upcoming, key=lambda coupon: coupon.coupon_date)
