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
        account_id: str,
    ) -> None:
        """
        Args:
            client:
                Авторизованный SDK клиент.

            account_id:
                Брокерский счёт.
        """

        self._client = client
        self._account_id = account_id

        self._validate_account()

    def _validate_account(self) -> None:
        """
        Проверяет доступность счёта.

        Raises:
            InvestAccountAccessError:
                Если счёт недоступен.
        """

        accounts = (self._client.users.get_accounts())

        available_ids = {
            account.id
            for account in accounts.accounts
        }

        if self._account_id not in available_ids:
            raise InvestAccountAccessError(f"Аккаунт: {self._account_id} недоступен")

    def get_portfolio(self):
        """
        Возвращает портфель пользователя.
        """

        return (
            self._client.operations
            .get_portfolio(
                account_id=self._account_id
            )
        )

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

        response = (
            self._client.instruments.get_bond_coupons(
                figi=figi,
                from_=datetime.now(),
                to=datetime.now().replace(
                    year=datetime.now().year + 1
                ),
            )
        )

        if not response.events:
            return None

        return sorted(
            response.events,
            key=lambda coupon: coupon.coupon_date,
        )[0]
