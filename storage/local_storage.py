import pandas as pd
from pathlib import Path
from typing import Optional
from datetime import datetime
from config.settings import RAW_DATA_DIR, PROCESSED_DATA_DIR, DATA_RETENTION_DAYS
from utils.logger import get_logger


class LocalStorage:
    def __init__(self):
        self.logger = get_logger("LocalStorage")
        RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    def save_raw_market(self, df: pd.DataFrame, suffix: str = "全市场") -> bool:
        return self._save_csv(df, RAW_DATA_DIR / "market", suffix)

    def save_realtime_volume(self, df: pd.DataFrame, symbol: str) -> bool:
        return self._save_csv(df, RAW_DATA_DIR / "realtime_volume", f"{symbol}_{datetime.now().strftime('%Y%m%d')}")

    def save_daily_history(self, df: pd.DataFrame, symbol: str) -> bool:
        return self._save_csv(df, RAW_DATA_DIR / "daily_history", symbol)

    def save_minute_data(self, df: pd.DataFrame, symbol: str) -> bool:
        return self._save_csv(df, RAW_DATA_DIR / "minute", f"{symbol}_{datetime.now().strftime('%Y%m%d')}")

    def save_processed(self, df: pd.DataFrame, name: str) -> bool:
        return self._save_csv(df, PROCESSED_DATA_DIR, name)

    def _save_csv(self, df: pd.DataFrame, sub_dir: Path, filename: str) -> bool:
        try:
            sub_dir.mkdir(parents=True, exist_ok=True)
            file_path = sub_dir / f"{filename}.csv"
            if file_path.exists():
                existing = pd.read_csv(file_path, dtype_backend="numpy_nullable")
                combined = pd.concat([existing, df], ignore_index=True)
                combined.drop_duplicates(inplace=True)
                combined.to_csv(file_path, index=False, encoding="utf-8-sig")
            else:
                df.to_csv(file_path, index=False, encoding="utf-8-sig")
            self.logger.info(f"数据已保存: {file_path} ({len(df)} 条)")
            return True
        except Exception as e:
            self.logger.error(f"数据保存失败 [{filename}]: {e}")
            return False

    def load_daily_history(self, symbol: str) -> Optional[pd.DataFrame]:
        file_path = RAW_DATA_DIR / "daily_history" / f"{symbol}.csv"
        if file_path.exists():
            return pd.read_csv(file_path, encoding="utf-8-sig")
        self.logger.warning(f"历史数据文件不存在: {file_path}")
        return None

    def load_market_snapshot(self, suffix: str = "全市场") -> Optional[pd.DataFrame]:
        files = sorted((RAW_DATA_DIR / "market").glob(f"*{suffix}*.csv"), reverse=True)
        if files:
            return pd.read_csv(files[0], encoding="utf-8-sig")
        return None

    def cleanup_old_data(self, days: int = DATA_RETENTION_DAYS) -> int:
        cutoff = datetime.now().timestamp() - days * 86400
        removed = 0
        for f in RAW_DATA_DIR.rglob("*.csv"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        self.logger.info(f"清理过期数据文件: {removed} 个")
        return removed
