import requests
import json
import pandas as pd
import os
from typing import Optional
from datetime import datetime, timedelta
from pathlib import Path
from collector.base import BaseCollector
from config.settings import MAX_HISTORY_DAYS, DATA_DIR


class HistoryCollector(BaseCollector):
    def __init__(self):
        super().__init__()
        self.name = "A股历史量价数据采集器"
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        self._cache_dir = DATA_DIR / "raw" / "history"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_daily_kline(self, symbol: str, days: int = MAX_HISTORY_DAYS) -> Optional[pd.DataFrame]:
        cached = self._load_cache(symbol)
        today_dt = datetime.now()
        today_str = today_dt.strftime("%Y-%m-%d")
        if cached is not None and not cached.empty:
            last_date = cached["日期"].max()
            has_today = last_date >= today_str
            sliced = self._slice_days(cached, days)
            if has_today:
                cached_start = cached["日期"].min()
                covered_days = (today_dt - datetime.strptime(cached_start, "%Y-%m-%d")).days
                if covered_days >= max(days - 5, 10):
                    return sliced
        result = self._fetch_from_api(symbol, days)
        if result is not None:
            self._save_cache(symbol, result)
        return result

    def _get_prefixed_codes(self, symbol: str) -> list:
        sym = symbol.replace("sh", "").replace("sz", "").replace("bj", "")
        prefixes = []
        if sym.startswith(("6", "9")):
            prefixes = ["sh"]
        elif sym.startswith(("0", "3", "2")):
            prefixes = ["sz"]
        elif sym.startswith(("4", "8")):
            prefixes = ["bj"]
        else:
            prefixes = ["sh", "sz"]
        return [f"{p}{sym}" for p in prefixes] + [sym]

    def _fetch_from_api(self, symbol: str, days: int) -> Optional[pd.DataFrame]:
        today = datetime.now()
        start = today - timedelta(days=days)
        candidates = self._get_prefixed_codes(symbol)
        api_symbol = candidates[0]
        all_rows = []
        for year in range(start.year, today.year + 1):
            params = {
                "_var": f"kline_day{year}",
                "param": f"{api_symbol},day,{year}-01-01,{year}-12-31,640,qfq",
                "r": "0.8205512681390605",
            }
            try:
                resp = self._session.get(
                    "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get",
                    params=params, timeout=15
                )
                for candidate in candidates:
                    day_data = self._parse_history_response(resp.text, candidate)
                    if day_data:
                        all_rows.extend(day_data)
                        break
            except Exception as e:
                self.logger.debug(f"获取 {symbol} {year} 年数据失败: {e}")
        if not all_rows:
            self.logger.debug(f"历史数据为空: {symbol}")
            return None
        records = []
        seen = set()
        for row in all_rows:
            try:
                date_str = row[0]
                if date_str in seen:
                    continue
                seen.add(date_str)
                if date_str < start.strftime("%Y-%m-%d"):
                    continue
                records.append({
                    "日期": date_str,
                    "开盘": float(row[1]),
                    "收盘": float(row[2]),
                    "最高": float(row[3]),
                    "最低": float(row[4]),
                    "成交量": float(row[5]),
                    "成交额": float(row[8]) / 10000 if len(row) > 8 and row[8] else 0,
                })
            except (IndexError, ValueError):
                continue
        if not records:
            return None
        df = pd.DataFrame(records)
        df.sort_values("日期", inplace=True)
        df.drop_duplicates(subset=["日期"], inplace=True)
        df.reset_index(drop=True, inplace=True)
        self.logger.debug(f"日线历史获取成功: {symbol}, {len(df)} 条")
        return df

    def _parse_history_response(self, text: str, key: str) -> Optional[list]:
        if "=" not in text or "{" not in text:
            return None
        try:
            json_str = text[text.index("{"):text.rindex("}") + 1]
            data = json.loads(json_str)
            node = data.get("data", {})
            val = node.get(key)
            if val is None:
                return None
            if isinstance(val, dict):
                for sub_key in ("qfqday", "day", "week", "month"):
                    if sub_key in val:
                        return val[sub_key]
            if isinstance(val, list):
                return val
        except Exception:
            pass
        return None

    def _load_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        path = self._cache_dir / f"{symbol}.csv"
        if path.exists():
            try:
                df = pd.read_csv(path, encoding="utf-8-sig")
                if "日期" in df.columns and not df.empty:
                    return df
            except Exception:
                pass
        return None

    def _save_cache(self, symbol: str, df: pd.DataFrame):
        if df is None or df.empty:
            return
        path = self._cache_dir / f"{symbol}.csv"
        try:
            old = self._load_cache(symbol)
            if old is not None and not old.empty:
                combined = pd.concat([old, df], ignore_index=True)
                combined.drop_duplicates(subset=["日期"], keep="last", inplace=True)
                combined.sort_values("日期", inplace=True)
                combined.to_csv(path, index=False, encoding="utf-8-sig")
            else:
                df.to_csv(path, index=False, encoding="utf-8-sig")
        except Exception as e:
            self.logger.debug(f"缓存写入失败 {symbol}: {e}")

    def _slice_days(self, df: pd.DataFrame, days: int) -> pd.DataFrame:
        if df is None or df.empty:
            return df
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        sliced = df[df["日期"] >= cutoff].copy()
        return sliced if not sliced.empty else df

    def fetch_weekly_kline(self, symbol: str, days: int = MAX_HISTORY_DAYS) -> Optional[pd.DataFrame]:
        return self.fetch_daily_kline(symbol, days).iloc[::5] if self.fetch_daily_kline(symbol, days) is not None else None

    def fetch_stock_info(self, symbol: str) -> Optional[dict]:
        df = self.safe_fetch(self._get_spot_with_ak, symbol)
        if df is not None and not df.empty:
            return df.iloc[0].to_dict()
        return None

    def _get_spot_with_ak(self, symbol):
        import akshare as ak
        return ak.stock_zh_a_spot()

    def fetch(self, symbol: str, days: int = MAX_HISTORY_DAYS) -> pd.DataFrame:
        df = self.fetch_daily_kline(symbol, days)
        return df if df is not None else pd.DataFrame()

    def clear_cache(self, symbol: str = None):
        if symbol:
            path = self._cache_dir / f"{symbol}.csv"
            if path.exists():
                path.unlink()
        else:
            for f in self._cache_dir.glob("*.csv"):
                f.unlink()
