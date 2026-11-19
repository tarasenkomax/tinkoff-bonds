from __future__ import annotations

import calendar
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from t_tech.invest.schemas import Bond, OperationState, OperationType, PortfolioPosition

from bonds.adapter import TinkoffInvestAdapter
from bonds.mixins import MoneyFormatterMixin
from bonds.ratings import get_rating
from bonds.schemas import (
    AggregatedBondPosition,
    BondInfo,
    BondPortfolioInfo,
    CouponCalendar,
    CouponDay,
    CouponMonth,
    CouponPayment,
    _BondMetrics,
)


class BondService(MoneyFormatterMixin):
    """Сервис получения информации об облигациях пользователя."""

    TAX_RATE = Decimal('0.13')
    MAX_WORKERS = 3
    CALENDAR_MONTHS = 12

    MOSCOW_TZ = ZoneInfo('Europe/Moscow')

    MONTHS = (
        'ЯНВАРЬ',
        'ФЕВРАЛЬ',
        'МАРТ',
        'АПРЕЛЬ',
        'МАЙ',
        'ИЮНЬ',
        'ИЮЛЬ',
        'АВГУСТ',
        'СЕНТЯБРЬ',
        'ОКТЯБРЬ',
        'НОЯБРЬ',
        'ДЕКАБРЬ',
    )

    def __init__(self, adapter: TinkoffInvestAdapter) -> None:
        self._adapter = adapter
        self._metrics_cache: list[_BondMetrics] | None = None

    def get_portfolio_json(self, indent: int | None = 4) -> str:
        """
        Сформировать единый JSON со сводной информацией и списком облигаций.

        :param indent: отступы для форматирования JSON (None для минификации)
        :return: JSON-строка
        """
        portfolio_info = self._get_portfolio_info()
        bonds = self._get_bonds()

        payload = {
            'portfolio_info': portfolio_info.to_dict(),
            'bonds': [bond.to_dict() for bond in bonds],
        }

        return json.dumps(payload, indent=indent, ensure_ascii=False, default=str)

    def get_coupon_calendar_json(self, indent: int | None = 4) -> str:
        """
        Сформировать JSON календаря купонных выплат на ближайшие 12 месяцев.

        Период начинается с первого числа текущего месяца.

        :param indent: отступы для форматирования JSON
        :return: JSON-строка с календарём купонных выплат
        """
        now = datetime.now(self.MOSCOW_TZ)
        today = now.date()

        start_date = today.replace(day=1)
        end_date = self._get_calendar_end_date(start_date)

        metrics = self._collect_bond_metrics()

        if not metrics:
            calendar_data = CouponCalendar(
                current_date=today,
                months=[],
            )

            return json.dumps(
                calendar_data.to_dict(),
                indent=indent,
                ensure_ascii=False,
            )

        operations = self._get_current_month_coupon_operations(
            start_date=start_date,
            now=now,
            metrics=metrics,
        )

        paid_by_figi = self._aggregate_paid_coupons(operations)
        coupon_events = self._get_coupon_events(metrics)

        months = self._build_coupon_calendar(
            metrics=metrics,
            coupon_events=coupon_events,
            paid_by_figi=paid_by_figi,
            start_date=start_date,
            end_date=end_date,
            today=today,
        )

        calendar_data = CouponCalendar(
            current_date=today,
            months=months,
        )

        return json.dumps(
            calendar_data.to_dict(),
            indent=indent,
            ensure_ascii=False,
        )

    @classmethod
    def _get_calendar_end_date(cls, start_date: date) -> date:
        """
        Получить последний день месяца, завершающего календарный период.

        :param start_date: первый день текущего месяца
        :return: последний день последнего месяца периода
        """
        month_index = (start_date.year * 12 + start_date.month - 1 + cls.CALENDAR_MONTHS - 1)

        year, month_index = divmod(month_index, 12)
        month = month_index + 1

        last_day = calendar.monthrange(year, month)[1]

        return date(year, month, last_day)

    def _get_current_month_coupon_operations(
        self,
        start_date: date,
        now: datetime,
        metrics: list[_BondMetrics],
    ) -> list[Any]:
        """
        Получить фактически выплаченные купоны за текущий месяц.

        Учитываются только исполненные операции выплаты купонов
        по облигациям, присутствующим в текущем портфеле.

        :param start_date: первый день текущего месяца
        :param now: текущее время в московском часовом поясе
        :param metrics: метрики облигаций портфеля
        :return: список купонных операций
        """
        start_datetime = datetime.combine(
            start_date,
            time.min,
            tzinfo=self.MOSCOW_TZ,
        ).astimezone(timezone.utc)

        end_datetime = now.astimezone(timezone.utc)

        portfolio_figis = {metric.position.figi for metric in metrics}

        operations = self._adapter.get_all_operations(
            from_date=start_datetime,
            to_date=end_datetime,
        )

        return [
            operation for operation in operations if (
                operation.operation_type == OperationType.OPERATION_TYPE_COUPON
                and operation.state == OperationState.OPERATION_STATE_EXECUTED and operation.figi in portfolio_figis
            )
        ]

    def _aggregate_paid_coupons(
        self,
        operations: list[Any],
    ) -> dict[str, Decimal]:
        """
        Сгруппировать фактически выплаченные купоны по FIGI.

        :param operations: список купонных операций
        :return: словарь FIGI -> сумма выплаченных купонов
        """
        paid_by_figi: dict[str, Decimal] = defaultdict(Decimal)

        for operation in operations:
            paid_by_figi[operation.figi] += self._money_to_decimal(operation.payment)

        return dict(paid_by_figi)

    def _get_coupon_events(
        self,
        metrics: list[_BondMetrics],
    ) -> dict[str, list[Any]]:
        """
        Получить купонные события для всех облигаций портфеля.

        Запросы к SDK выполняются параллельно.

        :param metrics: метрики облигаций портфеля
        :return: словарь FIGI -> список купонных событий
        """
        if not metrics:
            return {}

        result: dict[str, list[Any]] = {}

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
            events = pool.map(
                self._adapter.get_bond_coupons,
                [metric.position.figi for metric in metrics],
            )

            for metric, bond_events in zip(metrics, events):
                result[metric.position.figi] = bond_events

        return result

    def _build_coupon_calendar(
        self,
        metrics: list[_BondMetrics],
        coupon_events: dict[str, list[Any]],
        paid_by_figi: dict[str, Decimal],
        start_date: date,
        end_date: date,
        today: date,
    ) -> list[CouponMonth]:
        """
        Сформировать календарь купонных выплат на {CALENDAR_MONTHS} календарных месяцев.

        Для флоатеров с неопределённым размером будущего купона используется
        последнее известное значение. Такой размер является прогнозным.

        :param metrics: метрики облигаций портфеля
        :param coupon_events: купонные события, сгруппированные по FIGI
        :param paid_by_figi: фактически выплаченные суммы по FIGI
        :param start_date: начало календарного периода
        :param end_date: конец календарного периода
        :param today: текущая дата
        :return: список месяцев с купонными выплатами
        """
        bonds_by_figi = {metric.position.figi: metric for metric in metrics}

        payments_by_date: dict[date, list[CouponPayment]] = defaultdict(list)

        for figi, events in coupon_events.items():
            metric = bonds_by_figi[figi]
            quantity = metric.position.quantity

            last_known_coupon = metric.next_coupon

            valid_events = [event for event in events if event.coupon_date is not None]

            for event in sorted(
                    valid_events,
                    key=lambda item: self._get_coupon_local_date(item.coupon_date),
            ):
                coupon_before_tax = self._money_to_decimal(event.pay_one_bond)

                if coupon_before_tax > 0:
                    last_known_coupon = coupon_before_tax
                elif metric.bond.floating_coupon_flag:
                    coupon_before_tax = last_known_coupon

                coupon_date = self._get_coupon_local_date(event.coupon_date)

                if not start_date <= coupon_date <= end_date:
                    continue

                coupon_per_bond = self._calculate_coupon_after_tax(coupon_before_tax)
                total_amount = coupon_per_bond * Decimal(quantity)

                payments_by_date[coupon_date].append(
                    CouponPayment(
                        bond_name=metric.bond.name,
                        quantity=quantity,
                        coupon_per_bond=coupon_per_bond,
                        total_amount=total_amount,
                    ),
                )

        months: list[CouponMonth] = []
        current_month = start_date.replace(day=1)

        while current_month <= end_date:
            year = current_month.year
            month = current_month.month

            month_start = current_month
            month_end = date(
                year,
                month,
                calendar.monthrange(year, month)[1],
            )

            month_payments = {
                payment_date: payments
                for payment_date, payments in payments_by_date.items()
                if month_start <= payment_date <= month_end
            }

            total_amount = sum(
                (payment.total_amount for payments in month_payments.values() for payment in payments),
                Decimal(0),
            )

            is_current_month = (current_month.year == today.year and current_month.month == today.month)

            days = self._build_month_days(
                month_payments=month_payments,
                month_start=month_start,
                month_end=month_end,
                today=today,
                is_current_month=is_current_month,
            )

            if is_current_month:
                paid_amount = sum(paid_by_figi.values(), Decimal(0))

                month_data = CouponMonth(
                    year=year,
                    month=month,
                    name=self.MONTHS[month - 1],
                    is_current_month=True,
                    total_amount=total_amount,
                    days=days,
                    paid_amount=paid_amount,
                    remaining_amount=total_amount - paid_amount,
                )
            else:
                month_data = CouponMonth(
                    year=year,
                    month=month,
                    name=self.MONTHS[month - 1],
                    is_current_month=False,
                    total_amount=total_amount,
                    days=days,
                )

            months.append(month_data)

            if month == 12:
                current_month = date(year + 1, 1, 1)
            else:
                current_month = date(year, month + 1, 1)

        return months

    @staticmethod
    def _build_month_days(
        month_payments: dict[date, list[CouponPayment]],
        month_start: date,
        month_end: date,
        today: date,
        is_current_month: bool,
    ) -> list[CouponDay]:
        """
        Сформировать дни месяца с купонными выплатами.

        Текущая дата добавляется всегда, даже если выплат в этот день нет.

        :param month_payments: выплаты, сгруппированные по датам
        :param month_start: первый день месяца
        :param month_end: последний день месяца
        :param today: текущая дата
        :param is_current_month: является ли месяц текущим
        :return: список дней с выплатами
        """
        days: list[CouponDay] = []

        for payment_date in sorted(month_payments):
            payments = sorted(
                month_payments[payment_date],
                key=lambda payment: payment.bond_name.lower(),
            )

            days.append(
                CouponDay(
                    date=payment_date,
                    label=payment_date.strftime('%d.%m'),
                    is_today=payment_date == today,
                    payments=payments,
                ),
            )

        if is_current_month and month_start <= today <= month_end:
            today_exists = any(day.date == today for day in days)

            if not today_exists:
                days.append(
                    CouponDay(
                        date=today,
                        label=today.strftime('%d.%m'),
                        is_today=True,
                        payments=[],
                    ),
                )

        return sorted(days, key=lambda day: day.date)

    def _get_coupon_local_date(self, coupon_date: datetime) -> date:
        """
        Получить дату купонного события в московском часовом поясе.

        :param coupon_date: дата купонного события из SDK
        :return: локальная дата
        """
        if coupon_date.tzinfo is None:
            coupon_date = coupon_date.replace(tzinfo=timezone.utc)

        return coupon_date.astimezone(self.MOSCOW_TZ).date()

    def _get_bonds(self) -> list[BondInfo]:
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

    def _get_portfolio_info(self) -> BondPortfolioInfo:
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

        Сетевые вызовы и расчёты выполняются один раз, результат переиспользуется в `_get_bonds` и `_get_portfolio_info`
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

    @staticmethod
    def _calculate_coupon_yield_before_tax(
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
