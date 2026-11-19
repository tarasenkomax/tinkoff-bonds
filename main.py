from t_tech.invest import Client

from bonds.adapter import TinkoffInvestAdapter
from bonds.conf import TINKOFF_BROKER_ACCOUNT_IDS, TINKOFF_TOKEN
from bonds.report import BondReport
from bonds.service import BondService
from bonds.utils import timed


@timed
def main() -> None:
    """Точка входа приложения."""
    with Client(TINKOFF_TOKEN) as client:
        adapter = TinkoffInvestAdapter(
            client=client,
            account_ids=TINKOFF_BROKER_ACCOUNT_IDS,
        )
        service = BondService(adapter)
        report = BondReport()

        portfolio_json = service.get_portfolio_json()
        report.save_to_file(json_str=portfolio_json, directory='json_dumps/portfolio')
        report.print_portfolio_info_from_json(portfolio_json)

        coupon_calendar_json = service.get_coupon_calendar_json()
        # report.save_to_file(coupon_calendar_json, 'json_dumps/coupon_calendar', filename_prefix='calendar')
        report.print_coupon_months_from_json(coupon_calendar_json)

        # report.print_coupon_calendar_from_json(coupon_calendar_json)


if __name__ == '__main__':
    main()
