from bonds.adapter import TinkoffInvestAdapter
from bonds.report import BondReport
from bonds.service import BondService
from bonds.utils import timed
from conf import TINKOFF_BROKER_ACCOUNT_IDS, TINKOFF_TOKEN
from t_tech.invest import Client


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

        filepath = report.save_to_file(portfolio_json)
        print(f'[INFO] Данные сохранены в файл: {filepath}')

        report.print_from_json(portfolio_json)


if __name__ == '__main__':
    main()
