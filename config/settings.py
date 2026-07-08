import os
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
LOG_DIR = DATA_DIR / "logs"

STOCK_MARKET = "A股"
TRADING_CYCLE = "超短线1-5日"

REALTIME_UPDATE_INTERVAL = 3
MONITOR_STOCK_LIST_PATH = PROJECT_ROOT / "config" / "monitor_stocks.csv"

DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_MAX_TOKENS = 4096
DEEPSEEK_TEMPERATURE = 0.3

DATA_RETENTION_DAYS = 120
MAX_HISTORY_DAYS = 365

WECHAT_WEBHOOK = os.environ.get("WECHAT_WEBHOOK", "")
SEND_KEY = os.environ.get("SEND_KEY", "")
