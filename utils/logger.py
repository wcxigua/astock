import sys
from pathlib import Path
from loguru import logger
from config.settings import LOG_DIR


LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()

logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{name}</cyan> | {message}",
    level="INFO",
    colorize=True,
)

logger.add(
    LOG_DIR / "system_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    encoding="utf-8",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{line} | {message}",
)

logger.add(
    LOG_DIR / "error_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    encoding="utf-8",
    level="ERROR",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{line} | {message}",
)


def get_logger(name: str):
    return logger.bind(name=name)
