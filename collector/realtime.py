import requests
import pandas as pd
from typing import Optional, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collector.base import BaseCollector


STOCK_LIST_PATH = Path(__file__).resolve().parent.parent / "config" / "monitor_stocks.csv"
_BATCH = 200


class RealtimeCollector(BaseCollector):
    def __init__(self):
        super().__init__()
        self.name = "A股实时行情采集器"

    def fetch_all_market(self) -> Optional[pd.DataFrame]:
        codes = self._load_codes()
        if not codes:
            return None

        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        all_rows = []
        batches = [codes[i:i + _BATCH] for i in range(0, len(codes), _BATCH)]

        with ThreadPoolExecutor(max_workers=3) as ex:
            fut_map = {ex.submit(self._fetch_batch, b, session): b for b in batches}
            for fut in as_completed(fut_map):
                try:
                    rows = fut.result()
                    if rows:
                        all_rows.extend(rows)
                except Exception as e:
                    self.logger.error(f"批次查询异常: {e}")

        if all_rows:
            df = pd.DataFrame(all_rows)
            self.logger.info(f"全市场行情抓取成功: {len(df)} 只")
            return df
        return None

    def _fetch_batch(self, codes: List[str], session: requests.Session = None) -> Optional[List[dict]]:
        try:
            url = f"https://qt.gtimg.cn/q={','.join(codes)}"
            s = session or requests.Session()
            s.headers.update({"User-Agent": "Mozilla/5.0"}) if not session else None
            resp = s.get(url, timeout=15)
            rows = []
            for line in resp.text.strip().split("\n"):
                parsed = self._parse_tx(line)
                if parsed:
                    rows.append(parsed)
            return rows
        except Exception:
            return None

    def _load_codes(self) -> List[str]:
        path = STOCK_LIST_PATH
        if path.exists():
            df = pd.read_csv(path, encoding="utf-8-sig")
            raw = df["代码"].dropna().astype(str).tolist()
            return [self._to_tx(c) for c in raw]
        self.logger.error(f"股票列表文件不存在: {path}")
        return []

    def _to_tx(self, code: str) -> str:
        code = str(code).strip()
        if code.startswith(("sh", "sz", "bj")):
            return code
        if code.startswith(("6", "9")):
            return f"sh{code}"
        if code[0] in ("0", "3", "2", "1"):
            return f"sz{code}"
        if code[0] in ("4", "8"):
            return f"bj{code}"
        return f"sz{code}"

    def fetch_single_quote(self, symbol: str) -> Optional[dict]:
        symbol = self._to_tx(symbol)
        try:
            url = f"https://qt.gtimg.cn/q={symbol}"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            for line in resp.text.strip().split("\n"):
                parsed = self._parse_tx(line)
                if parsed:
                    return parsed
        except Exception as e:
            self.logger.error(f"个股行情获取失败 [{symbol}]: {e}")
        return None

    def _parse_tx(self, line: str) -> Optional[dict]:
        if not line or "=" not in line:
            return None
        raw = line.split("=", 1)[1].strip().strip('"').strip(";").strip('"')
        fields = raw.split("~")
        if len(fields) < 40:
            return None
        def sf(v):
            try: return float(v) if v else 0.0
            except: return 0.0
        return {
            "代码": fields[2], "名称": fields[1],
            "最新价": sf(fields[3]), "昨收": sf(fields[4]),
            "今开": sf(fields[5]), "成交量": sf(fields[6]),
            "外盘": sf(fields[7]), "内盘": sf(fields[8]),
            "买一价": sf(fields[9]), "卖一价": sf(fields[21]),
            "最高": sf(fields[33]) if len(fields) > 33 else 0,
            "最低": sf(fields[34]) if len(fields) > 34 else 0,
            "数据时间": fields[30] if len(fields) > 30 else "",
        }

    def fetch_realtime_by_symbols(self, symbols: List[str]) -> Optional[pd.DataFrame]:
        tx_symbols = [s if s.startswith(("sh", "sz", "bj")) else self._to_tx(s) for s in symbols]
        all_rows = []
        batches = [tx_symbols[i:i + _BATCH] for i in range(0, len(tx_symbols), _BATCH)]
        with ThreadPoolExecutor(max_workers=16) as ex:
            for r in ex.map(self._fetch_batch, batches):
                if r:
                    all_rows.extend(r)
        if all_rows:
            return pd.DataFrame(all_rows)
        return None

    def fetch_inner_outer_volume(self, symbol: str) -> Optional[dict]:
        q = self.fetch_single_quote(symbol)
        if q:
            return {"symbol": symbol, "内盘": q.get("内盘", 0), "外盘": q.get("外盘", 0)}
        return None

    def fetch(self, **kwargs) -> pd.DataFrame:
        df = self.fetch_all_market()
        return df if df is not None else pd.DataFrame()
