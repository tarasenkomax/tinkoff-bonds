import os

from dotenv import load_dotenv


load_dotenv()

TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')


def _parse_account_ids(raw: str | None) -> list[str]:
    """
    Разобрать строку с идентификаторами счетов в список.

    Идентификаторы разделяются запятыми. Пробелы вокруг
    идентификаторов игнорируются, пустые значения отбрасываются.

    :param raw: строка из переменной окружения или ``None``
    :return: список идентификаторов счетов
    """
    if not raw:
        return []

    return [item.strip() for item in raw.split(',') if item.strip()]


TINKOFF_BROKER_ACCOUNT_IDS: list[str] = _parse_account_ids(os.getenv('TINKOFF_BROKER_ACCOUNT_IDS'))
