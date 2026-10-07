import os

from dotenv import load_dotenv


load_dotenv()

TINKOFF_TOKEN = os.getenv('TINKOFF_TOKEN')
TINKOFF_BROKER_ACCOUNT_ID = os.getenv('TINKOFF_BROKER_ACCOUNT_ID')
TINKOFF_IIS_ACCOUNT_ID = os.getenv('TINKOFF_IIS_ACCOUNT_ID')
