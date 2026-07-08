from typing import Optional, Dict, Any
import pandas as pd
from utils.logger import get_logger


class DataChannel:
    def __init__(self):
        self.logger = get_logger("DataChannel")
        self._latest_market_snapshot: Optional[pd.DataFrame] = None
        self._latest_volume_data: Dict[str, Any] = {}

    def ingest_market_snapshot(self, df: pd.DataFrame) -> bool:
        if df is None or df.empty:
            self.logger.warning("接收到空行情数据")
            return False
        self._latest_market_snapshot = df.copy()
        self.logger.info(f"行情快照已摄入: {len(df)} 条记录")
        return True

    def ingest_volume_data(self, symbol: str, data: Dict[str, Any]) -> bool:
        self._latest_volume_data[symbol] = data
        self.logger.info(f"量能数据已摄入: {symbol}")
        return True

    def get_market_snapshot(self) -> Optional[pd.DataFrame]:
        return self._latest_market_snapshot

    def get_volume_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._latest_volume_data.get(symbol)

    def build_model_input(self, top_n: int = 50) -> Optional[Dict[str, Any]]:
        if self._latest_market_snapshot is None:
            return None
        df = self._latest_market_snapshot.copy()
        volume_cols = [c for c in df.columns if "量" in str(c) or "换手" in str(c)]
        top_volume = df.nlargest(top_n, "成交量") if "成交量" in df.columns else df.head(top_n)
        input_data = {
            "market_overview": {
                "total_stocks": len(df),
                "top_volume_stocks": top_volume.to_dict(orient="records") if not top_volume.empty else [],
            },
            "volume_fields_available": volume_cols,
            "individual_volume_data": self._latest_volume_data,
        }
        return input_data
