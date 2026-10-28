from __future__ import annotations

import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

from bonds.adapter import TinkoffInvestAdapter
from bonds.mixins import MoneyFormatterMixin
from bonds.ratings import get_rating
from bonds.schemas import (
    AggregatedBondPosition,
    BondInfo,
    BondPortfolioInfo,
    _BondMetrics,
)
from t_tech.invest.schemas import Bond, PortfolioPosition


class BondService(MoneyFormatterMixin):
    """Сервис получения информации об облигациях пользователя."""

    TAX_RATE = Decimal('0.13')
    MAX_WORKERS = 3

    def __init__(self, adapter: TinkoffInvestAdapter) -> None:
        self._adapter = adapter
        self._metrics_cache: list[_BondMetrics] | None = None

    def get_bonds(self) -> list[BondInfo]:
        """
        Вернуть информацию обо всех облигациях со всех счетов.

        :return: список облигаций, отсортированный по имени
        """
        metrics = self._collect_bond_metrics()
        if not metrics:
            return []

        total_bonds_quantity = sum(metric.position.quantity for metric in metrics)
        company_shares = self._calculate_company_shares(metrics, total_bonds_quantity)

        bonds = [
            self._create_bond_info(
                metrics=metric,
                total_bonds_quantity=total_bonds_quantity,
                company_portfolio_percent=company_shares.get(self._get_company_key(metric.bond.name)),
            ) for metric in metrics
        ]

        return sorted(bonds, key=lambda bond: bond.name.lower())

    def _calculate_company_shares(
        self,
        metrics: list[_BondMetrics],
        total_bonds_quantity: int,
    ) -> dict[str, str | None]:
        """
        Рассчитать суммарный процент портфеля для компаний, у которых больше одной облигации.
        """
        company_stats = defaultdict(lambda: {'quantity': 0, 'bonds': set()})

        for metric in metrics:
            company = self._get_company_key(metric.bond.name)
            company_stats[company]['quantity'] += metric.position.quantity
            company_stats[company]['bonds'].add(metric.bond.name)

        shares = {}
        for company, stats in company_stats.items():
            if len(stats['bonds']) > 1:
                percent = Decimal(stats['quantity']) / Decimal(total_bonds_quantity) * Decimal(100)
                shares[company] = f'{percent:.2f}%'
            else:
                shares[company] = None

        return shares

    def get_portfolio_info(self) -> BondPortfolioInfo:
        """
        Вернуть сводную информацию по облигационному портфелю.

        В расчёте участвуют облигации со всех брокерских счетов.

        :return: DTO со сводной информацией по портфелю
        """
        metrics = self._collect_bond_metrics()

        total_quantity = sum(metric.position.quantity for metric in metrics)
        total_invested = sum(
            metric.position.average_position_price * Decimal(metric.position.quantity) for metric in metrics
        )
        current_value = sum(metric.position.current_price * Decimal(metric.position.quantity) for metric in metrics)
        change_percent = self._calculate_portfolio_change_percent(
            invested=total_invested,
            current_value=current_value,
        )

        total_coupon_before = sum(
            metric.annual_coupon_before_tax * Decimal(metric.position.quantity) for metric in metrics
        )
        total_coupon_after = sum(
            metric.annual_coupon_after_tax * Decimal(metric.position.quantity) for metric in metrics
        )

        annual_income_before_tax = total_coupon_before
        annual_income_after_tax = total_coupon_after

        monthly_income_before_tax = annual_income_before_tax / Decimal(12)
        monthly_income_after_tax = annual_income_after_tax / Decimal(12)

        weighted_ytm_before = sum(
            metric.ytm_before_tax * metric.position.average_position_price * Decimal(metric.position.quantity)
            for metric in metrics
        )
        weighted_ytm_after = sum(
            metric.ytm_after_tax * metric.position.average_position_price * Decimal(metric.position.quantity)
            for metric in metrics
        )

        if total_invested > 0:
            coupon_yield_before = total_coupon_before / total_invested * Decimal(100)
            coupon_yield_after = total_coupon_after / total_invested * Decimal(100)
            portfolio_ytm_before = weighted_ytm_before / total_invested
            portfolio_ytm_after = weighted_ytm_after / total_invested
        else:
            coupon_yield_before = Decimal(0)
            coupon_yield_after = Decimal(0)
            portfolio_ytm_before = Decimal(0)
            portfolio_ytm_after = Decimal(0)

        return BondPortfolioInfo(
            total_quantity=total_quantity,
            total_invested=total_invested,
            current_value=current_value,
            change_percent=change_percent,
            coupon_yield_before_tax=coupon_yield_before,
            coupon_yield_after_tax=coupon_yield_after,
            yield_to_maturity_before_tax=portfolio_ytm_before,
            yield_to_maturity_after_tax=portfolio_ytm_after,
            annual_income_before_tax=annual_income_before_tax,
            annual_income_after_tax=annual_income_after_tax,
            monthly_income_before_tax=monthly_income_before_tax,
            monthly_income_after_tax=monthly_income_after_tax,
        )

    def _collect_bond_metrics(self) -> list[_BondMetrics]:
        """
        Собрать метрики по всем облигациям портфеля.

        Сетевые вызовы (`get_bond_by_figi`, `get_next_bond_coupon`) выполняются параллельно в пуле потоков.

        Сетевые вызовы и расчёты выполняются один раз, результат переиспользуется в `get_bonds` и `get_portfolio_info`
        благодаря кешу `self._metrics_cache`.

        :return: список метрик по облигациям
        """
        if self._metrics_cache is not None:
            return self._metrics_cache

        positions = self._get_bonds_portfolio()

        if not positions:
            self._metrics_cache = []
            return []

        now = datetime.now(timezone.utc)

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
            bonds_future = pool.map(
                lambda position: self._adapter.get_bond_by_figi(position.figi),
                positions,
            )
            coupons_future = pool.map(
                lambda position: self._get_next_coupon(position.figi),
                positions,
            )
            bonds = list(bonds_future)
            coupons = list(coupons_future)

        metrics: list[_BondMetrics] = []

        for position, bond, coupon in zip(positions, bonds, coupons):
            if bond is None:
                continue

            price = position.average_position_price
            if price <= 0:
                continue

            annual_coupon_before = coupon * Decimal(bond.coupon_quantity_per_year)
            annual_coupon_after = self._calculate_coupon_after_tax(coupon) * Decimal(
                bond.coupon_quantity_per_year,
            )

            metrics.append(
                _BondMetrics(
                    position=position,
                    bond=bond,
                    next_coupon=coupon,
                    ytm_before_tax=self._calculate_yield_to_maturity(
                        bond=bond,
                        position=position,
                        coupon=coupon,
                        now=now,
                    ),
                    ytm_after_tax=self._calculate_yield_to_maturity(
                        bond=bond,
                        position=position,
                        coupon=coupon,
                        after_tax=True,
                        now=now,
                    ),
                    coupon_yield_before_tax=self._calculate_coupon_yield_before_tax(
                        bond=bond,
                        position=position,
                        next_coupon=coupon,
                    ),
                    coupon_yield_after_tax=self._calculate_coupon_yield_after_tax(
                        bond=bond,
                        position=position,
                        next_coupon=coupon,
                    ),
                    annual_coupon_before_tax=annual_coupon_before,
                    annual_coupon_after_tax=annual_coupon_after,
                ),
            )

        self._metrics_cache = metrics
        return metrics

    def _get_bonds_portfolio(self) -> list[AggregatedBondPosition]:
        """
        Вернуть агрегированные позиции по облигациям со всех счетов.

        :return: список агрегированных позиций по облигациям
        """

        portfolios = self._adapter.get_portfolios()

        positions = [
            position for portfolio in portfolios for position in portfolio.positions if self._is_bond(position)
        ]

        return self._aggregate_positions(positions)

    @staticmethod
    def _get_company_key(bond_name: str) -> str:
        """
        Получить ключ компании (эмитента) для группировки.

        Отрезает от названия номер выпуска (например, "001Р-01", "БО-П10", "26254").
        Пример: "АПРИ БО-002Р-13" -> "АПРИ"
        Пример: "ВИС ФИНАНС БО-П10" -> "ВИС ФИНАНС"
        Пример: "АФК Система БО 001Р-30" -> "АФК Система"
        """
        match = re.search(r'\s+(?:БО[- ]?\d|0\d|П\d|\d)', bond_name)

        if match:
            return bond_name[:match.start()].strip()

        match_bo = re.search(r'\s+БО', bond_name)
        if match_bo:
            return bond_name[:match_bo.start()].strip()

        return bond_name.strip()

    def _aggregate_positions(
        self,
        positions: list[PortfolioPosition],
    ) -> list[AggregatedBondPosition]:
        """
        Объединить позиции одной облигации со всех счетов.

        Позиции группируются по FIGI. Количество облигаций
        складывается. Цена покупки и текущая цена рассчитываются
        как средневзвешенные по количеству.

        :param positions: позиции облигаций со всех счетов
        :return: список агрегированных позиций
        """

        grouped: dict[str, list[PortfolioPosition]] = defaultdict(list)

        for position in positions:
            grouped[position.figi].append(position)

        result: list[AggregatedBondPosition] = []

        for figi, figi_positions in grouped.items():
            total_quantity = 0
            total_invested = Decimal(0)
            total_current_value = Decimal(0)

            for position in figi_positions:
                units = position.quantity.units
                if units == 0:
                    continue

                qty = Decimal(units)
                total_quantity += units
                total_invested += (self._money_to_decimal(position.average_position_price_fifo) * qty)
                total_current_value += (self._money_to_decimal(position.current_price) * qty)

            if total_quantity == 0:
                continue

            total_quantity_decimal = Decimal(total_quantity)

            result.append(
                AggregatedBondPosition(
                    figi=figi,
                    quantity=total_quantity,
                    average_position_price=total_invested / total_quantity_decimal,
                    current_price=total_current_value / total_quantity_decimal,
                ),
            )

        return result

    @staticmethod
    def _is_bond(position: PortfolioPosition) -> bool:
        """
        Проверить, является ли позиция облигацией.

        :param position: позиция портфеля
        :return: `True`, если позиция — облигация
        """

        return position.instrument_type == 'bond'

    @staticmethod
    def _calculate_position_percent(
        position: AggregatedBondPosition,
        total_bonds_quantity: int,
    ) -> Decimal:
        """
        Рассчитать долю облигации в портфеле.

        Доля считается по количеству облигаций, а не по стоимости.

        :param position: агрегированная позиция
        :param total_bonds_quantity: суммарное количество облигаций в портфеле
        :return: доля облигации в процентах
        """
        if total_bonds_quantity <= 0:
            return Decimal(0)

        return Decimal(position.quantity) / Decimal(total_bonds_quantity) * Decimal(100)

    def _calculate_yield_to_maturity(
        self,
        bond: Bond,
        position: AggregatedBondPosition,
        coupon: Decimal,
        after_tax: bool = False,
        now: datetime | None = None,
    ) -> Decimal:
        """
        Рассчитать приблизительную доходность облигации к погашению.

        Доходность рассчитывается по упрощённой формуле:
            (годовой купон + (номинал − цена) / лет до погашения) / цена * 100

        При `after_tax=True` годовой купон рассчитывается с учётом НДФЛ по ставке `TAX_RATE`. Доход от разницы между
        ценой покупки и номиналом при этом не изменяется.

        :param bond: информация об облигации, включая номинал, дату погашения и количество купонных выплат в год
        :param position: агрегированная позиция пользователя
        :param coupon: размер купона на одну облигацию до уплаты НДФЛ
        :param after_tax: если `True`, рассчитывает доходность с учётом НДФЛ на купонный доход
        :param now: момент времени для расчёта срока до погашения. Если не задан, берётся текущее время в UTC
        :return: приблизительная доходность к погашению в процентах
        """
        if not bond.maturity_date:
            return Decimal(0)

        price = position.average_position_price
        if price <= 0:
            return Decimal(0)

        nominal = self._money_to_decimal(bond.nominal)

        if now is None:
            now = datetime.now(timezone.utc)

        years_to_maturity = Decimal((bond.maturity_date - now).days) / Decimal(365)
        if years_to_maturity <= 0:
            return Decimal(0)

        if after_tax:
            coupon = self._calculate_coupon_after_tax(coupon)

        annual_coupon = coupon * Decimal(bond.coupon_quantity_per_year)
        redemption_gain = (nominal - price) / years_to_maturity
        ytm = (annual_coupon + redemption_gain) / price

        return ytm * Decimal(100)

    def _calculate_coupon_yield_before_tax(
        self,
        bond: Bond,
        position: AggregatedBondPosition,
        next_coupon: Decimal,
    ) -> Decimal:
        """
        Рассчитать текущую купонную доходность до НДФЛ.

        :param bond: информация об облигации
        :param position: агрегированная позиция пользователя
        :param next_coupon: размер ближайшего купона
        :return: купонная доходность в процентах
        """

        price = position.average_position_price

        if price <= 0 or next_coupon <= 0:
            return Decimal(0)

        annual_coupon = next_coupon * Decimal(bond.coupon_quantity_per_year)

        return annual_coupon / price * Decimal(100)

    def _calculate_coupon_yield_after_tax(
        self,
        bond: Bond,
        position: AggregatedBondPosition,
        next_coupon: Decimal,
    ) -> Decimal:
        """
        Рассчитать текущую купонную доходность после НДФЛ.

        :param bond: информация об облигации
        :param position: агрегированная позиция пользователя
        :param next_coupon: размер ближайшего купона
        :return: купонная доходность в процентах
        """

        price = position.average_position_price

        if price <= 0 or next_coupon <= 0:
            return Decimal(0)

        annual_coupon = (self._calculate_coupon_after_tax(next_coupon) * Decimal(bond.coupon_quantity_per_year))

        return annual_coupon / price * Decimal(100)

    def _get_next_coupon(
        self,
        figi: str,
    ) -> Decimal:
        """
        Вернуть размер ближайшего купона.

        :param figi: FIGI облигации
        :return: размер ближайшего купона или `0`, если купона нет
        """

        coupon = self._adapter.get_next_bond_coupon(figi)

        if coupon is None:
            return Decimal(0)

        return self._money_to_decimal(coupon.pay_one_bond)

    def _calculate_coupon_after_tax(
        self,
        coupon: Decimal,
    ) -> Decimal:
        """
        Рассчитать купон после НДФЛ.

        :param coupon: размер купона до налога
        :return: размер купона после удержания НДФЛ
        """
        return coupon * (Decimal(1) - self.TAX_RATE)

    @staticmethod
    def _calculate_portfolio_change_percent(
        invested: Decimal,
        current_value: Decimal,
    ) -> Decimal:
        """
        Рассчитать изменение стоимости портфеля в процентах.

        :param invested: сумма вложений
        :param current_value: текущая стоимость портфеля
        :return: изменение стоимости в процентах
        """
        if invested <= 0:
            return Decimal(0)

        return (current_value - invested) / invested * Decimal(100)

    def _create_bond_info(
        self,
        metrics: _BondMetrics,
        total_bonds_quantity: int,
        company_portfolio_percent: str | None = None,
    ) -> BondInfo:
        """
        Создать DTO с информацией об облигации.

        :param metrics: предварительно рассчитанные метрики по облигации
        :param total_bonds_quantity: суммарное количество облигаций в портфеле (для расчёта доли)
        :param company_portfolio_percent: суммарный процент портфеля для компании
        :return: DTO с информацией об облигации
        """
        bond = metrics.bond
        position = metrics.position
        prefix = '~' if bond.floating_coupon_flag else ''

        return BondInfo(
            name=bond.name,
            rating=get_rating(bond.name),
            maturity_date=self._format_maturity_date(bond),
            nominal=self._format_money(bond.nominal),
            amortization=self._bool_marker(bond.amortization_flag),
            floater=self._bool_marker(bond.floating_coupon_flag),
            buy_price=f'{position.average_position_price:.2f} ₽',
            quantity=position.quantity,
            coupons_per_year=bond.coupon_quantity_per_year,
            next_coupon_before_tax=f'{metrics.next_coupon:.2f} ₽',
            next_coupon_after_tax=f'{self._calculate_coupon_after_tax(metrics.next_coupon):.2f} ₽',
            portfolio_percent=f'{self._calculate_position_percent(position, total_bonds_quantity):.2f}%',
            company_portfolio_percent=company_portfolio_percent,
            yield_to_maturity=self._format_ytm(
                prefix=prefix,
                before_tax=metrics.ytm_before_tax,
                after_tax=metrics.ytm_after_tax,
            ),
            coupon_yield_before_tax=f'{metrics.coupon_yield_before_tax:.2f}%',
            coupon_yield_after_tax=f'{metrics.coupon_yield_after_tax:.2f}%',
        )

    @staticmethod
    def _format_maturity_date(bond: Bond) -> str:
        """
        Отформатировать дату погашения облигации.

        :param bond: информация об облигации
        :return: дата в формате `ДД.ММ.ГГГГ` или '-', если дата не задана
        """
        if not bond.maturity_date:
            return '-'

        return bond.maturity_date.strftime('%d.%m.%Y')

    @staticmethod
    def _format_ytm(prefix: str, before_tax: Decimal, after_tax: Decimal) -> str:
        """
        Отформатировать пару значений YTM (до/после НДФЛ).

        :param prefix: префикс (например, '~' для флоатеров)
        :param before_tax: доходность до НДФЛ
        :param after_tax: доходность после НДФЛ
        :return: строка вида `15.12% / 13.15%`
        """
        return f'{prefix}{before_tax:.2f}% / {prefix}{after_tax:.2f}%'

    @staticmethod
    def _bool_marker(value: bool) -> str:
        """
        Преобразовать булев флаг в символьный маркер.

        :param value: значение флага
        :return: '+' для `True`, '-' для `False`
        """
        return '+' if value else '-'
