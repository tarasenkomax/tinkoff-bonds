from __future__ import annotations

from datetime import datetime

from t_tech.invest import Client, InstrumentIdType

from .exceptions import InvestAccountAccessError


class TinkoffInvestAdapter:
    """
    Адаптер работы с конкретным брокерским счётом.

    Скрывает детали SDK от бизнес-кода.
    """

    def __init__(
        self,
        client: Client,
        account_ids: list[str],
    ) -> None:
        """
        Args:
            client:
                Авторизованный SDK клиент.

            account_ids:
                Идентификаторы брокерских счетов.
        """

        self._client = client
        self._account_ids = account_ids

        self._validate_accounts()

    def _validate_accounts(self) -> None:
        """
        Проверяет доступность всех указанных счетов.

        Raises:
            InvestAccountAccessError:
                Если хотя бы один счёт недоступен.
        """

        accounts = self._client.users.get_accounts()

        available_ids = {
            account.id
            for account in accounts.accounts
        }

        unavailable_ids = set(self._account_ids) - available_ids

        if unavailable_ids:
            raise InvestAccountAccessError(
                "Недоступны брокерские счета: "
                f"{', '.join(sorted(unavailable_ids))}"
            )

    def get_portfolios(self) -> list:
        """
        Возвращает портфели по всем брокерским счетам.

        Returns:
            Список портфелей.
        """

        return [
            self._client.operations.get_portfolio(
                account_id=account_id,
            )
            for account_id in self._account_ids
        ]

    def get_bond_by_figi(self, figi: str):
        """
        Получает информацию об облигации по FIGI.

        Args:
            figi:
                FIGI инструмента.

        Returns:
            Информация об облигации из SDK.
        """

        return (
            self._client.instruments.bond_by(
                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                id=figi,
            ).instrument
        )

    def get_bond_coupons(self, figi: str):
        """
        Возвращает список купонов облигации.

        Args:
            figi:
                FIGI облигации.

        Returns:
            Список купонных выплат.
        """

        response = self._client.instruments.get_bond_coupons(figi=figi)

        return response.events

    def get_next_bond_coupon(self, figi: str):
        """
        Возвращает ближайший купон по облигации.

        Args:
            figi:
                FIGI облигации.

        Returns:
            Ближайшая купонная выплата.
        """

        now = datetime.now()

        response = self._client.instruments.get_bond_coupons(
            figi=figi,
            from_=now,
            to=now.replace(year=now.year + 1),
        )

        if not response.events:
            return None

        return min(
            response.events,
            key=lambda coupon: coupon.coupon_date,
        )