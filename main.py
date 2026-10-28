from bonds.adapter import TinkoffInvestAdapter
from bonds.report import BondReport
from bonds.service import BondService
from bonds.utils import timed
from conf import TINKOFF_BROKER_ACCOUNT_IDS, TINKOFF_TOKEN
from t_tech.invest import Client


@timed
def main() -> None:
    """
    Точка входа приложения.
    """

    with Client(TINKOFF_TOKEN) as client:
        adapter = TinkoffInvestAdapter(
            client=client,
            account_ids=TINKOFF_BROKER_ACCOUNT_IDS,
        )

        bond_service = BondService(adapter)
        report = BondReport()

        portfolio_info = bond_service.get_portfolio_info()
        bonds = bond_service.get_bonds()

        report.print_portfolio_info(portfolio_info)
        report.print_bonds_table(bonds, portfolio_info)


if __name__ == '__main__':
    main()
