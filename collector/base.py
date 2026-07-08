from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import akshare as ak
import pandas as pd
from utils.logger import get_logger


class BaseCollector(ABC):
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self._session = None

    @abstractmethod
    def fetch(self, **kwargs) -> pd.DataFrame:
        pass

    def _validate_df(self, df: pd.DataFrame, required_cols: List[str]) -> bool:
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            self.logger.warning(f"缺少必要字段: {missing}")
            return False
        return True

    def safe_fetch(self, fetch_func, **kwargs) -> Optional[pd.DataFrame]:
        try:
            result = fetch_func(**kwargs)
            if result is None or (isinstance(result, pd.DataFrame) and result.empty):
                self.logger.warning(f"接口返回空数据: {fetch_func.__name__}")
                return None
            return result
        except Exception as e:
            self.logger.error(f"数据抓取失败 [{fetch_func.__name__}]: {e}")
            return None
