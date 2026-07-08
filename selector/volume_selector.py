import pandas as pd
import numpy as np
from typing import Optional, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from collector.realtime import RealtimeCollector
from collector.history import HistoryCollector
from utils.logger import get_logger


class VolumeSelector:
    def __init__(self):
        self.logger = get_logger("VolumeSelector")
        self.realtime = RealtimeCollector()
        self.history = HistoryCollector()

    def screen(self, market_df: pd.DataFrame = None) -> List[Dict]:
        if market_df is None or market_df.empty:
            market_df = self.realtime.fetch_all_market()
        if market_df is None or market_df.empty:
            return []

        df = market_df.copy()
        df.drop_duplicates(subset=["代码"], inplace=True)
        df = self._filter_st(df)
        df = self._filter_price(df)
        df = self._filter_low_volume(df)
        df = self._calc_change(df)

        codes = df["代码"].tolist()
        self.logger.info(f"待分析: {len(codes)} 只")

        results = []
        with ThreadPoolExecutor(max_workers=20) as ex:
            fut_map = {}
            for _, row in df.iterrows():
                code = row["代码"]
                fut = ex.submit(self._analyze_stock, code, row)
                fut_map[fut] = code
            for fut in as_completed(fut_map):
                try:
                    info = fut.result()
                    if info:
                        results.append(info)
                except Exception as e:
                    self.logger.debug(f"分析异常: {e}")

        results.sort(key=lambda x: x.get("综合得分", 0), reverse=True)
        self.logger.info(f"选股完成: 命中 {len(results)} 只")
        return results[:20]

    def _filter_st(self, df: pd.DataFrame) -> pd.DataFrame:
        if "名称" not in df.columns:
            return df
        mask = ~df["名称"].astype(str).str.contains("ST|退市|终止上市", na=False)
        before = len(df)
        df = df[mask].copy()
        self.logger.info(f"ST过滤: {before} -> {len(df)}")
        return df

    def _filter_price(self, df: pd.DataFrame, min_price: float = 3.0) -> pd.DataFrame:
        if "最新价" not in df.columns:
            return df
        mask = df["最新价"].astype(float) >= min_price
        before = len(df)
        df = df[mask].copy()
        self.logger.info(f"股价过滤(<{min_price}元): {before} -> {len(df)}")
        return df

    def _filter_low_volume(self, df: pd.DataFrame, min_volume: float = 1000) -> pd.DataFrame:
        if "成交量" not in df.columns:
            return df
        mask = df["成交量"].astype(float) >= min_volume
        before = len(df)
        df = df[mask].copy()
        self.logger.info(f"低量过滤(<{min_volume}手): {before} -> {len(df)}")
        return df

    def _calc_change(self, df: pd.DataFrame) -> pd.DataFrame:
        if "最新价" in df.columns and "昨收" in df.columns:
            yc = df["昨收"].astype(float).replace(0, np.nan)
            df["涨跌幅"] = ((df["最新价"].astype(float) - yc) / yc * 100).fillna(0)
        else:
            df["涨跌幅"] = 0
        return df

    def _analyze_stock(self, code: str, row: pd.Series) -> Optional[Dict]:
        try:
            hist = self.history.fetch_daily_kline(code, days=15)
            if hist is None or len(hist) < 10:
                return None

            recent_5 = hist.tail(5)["成交量"].mean() if len(hist) >= 5 else 0
            recent_10 = hist.tail(10)["成交量"].mean() if len(hist) >= 10 else 0
            today_vol = hist.iloc[-1]["成交量"] if not hist.empty else 0

            if recent_5 <= 0 or today_vol <= 0:
                return None

            vol_ratio = today_vol / recent_5
            vol_expand = (recent_5 / recent_10 - 1) * 100 if recent_10 > 0 else 0

            if vol_ratio < 1.8:
                return None
            if recent_5 <= recent_10 * 1.5:
                return None

            price = float(row["最新价"]) if "最新价" in row else 0
            change_pct = float(row["涨跌幅"]) if "涨跌幅" in row else 0
            name = str(row["名称"]) if "名称" in row else ""

            if change_pct < 0.5 and vol_ratio > 2.5:
                return None

            score = vol_ratio * 0.4 + vol_expand * 0.3 + change_pct * 0.2 + 0.1

            avg_price_5 = float(hist.tail(5)["收盘"].mean()) if len(hist) >= 5 else price
            avg_price_10 = float(hist.tail(10)["收盘"].mean()) if len(hist) >= 10 else price
            avg_price_20 = float(hist.tail(20)["收盘"].mean()) if len(hist) >= 20 else price
            recent_high = float(hist.tail(20)["最高"].max()) if len(hist) >= 20 else price
            recent_low = float(hist.tail(20)["最低"].min()) if len(hist) >= 20 else price
            ma_support = min(avg_price_5, avg_price_10, avg_price_20)
            price_above_ma5 = price > avg_price_5
            price_above_ma10 = price > avg_price_10
            vol_price_align = price_above_ma5 and price_above_ma10

            buy_zone_low = round(max(recent_low, ma_support) * 1.01, 2)
            buy_zone_high = round(min(recent_high * 0.98, avg_price_5 * 1.02), 2)
            if buy_zone_low > buy_zone_high:
                buy_zone_low, buy_zone_high = buy_zone_high, buy_zone_low
            suggested_buy = round((buy_zone_low + buy_zone_high) / 2, 2)

            if vol_ratio >= 2.5 and vol_expand >= 80 and vol_price_align:
                signal_level = "强信号"
                position_advice = "重仓"
                target_mult = 1.10
                stop_mult = 0.93
                hold_days = "1-3日"
            elif vol_ratio >= 1.8 and vol_expand >= 50 and price_above_ma5:
                signal_level = "中信号"
                position_advice = "半仓"
                target_mult = 1.08
                stop_mult = 0.95
                hold_days = "2-4日"
            else:
                signal_level = "弱信号"
                position_advice = "轻仓"
                target_mult = 1.05
                stop_mult = 0.97
                hold_days = "3-5日"

            target_profit = round(price * target_mult, 2)
            stop_loss = round(max(recent_low * stop_mult, price * 0.93), 2)
            stop_loss = min(stop_loss, round(price * 0.97, 2))

            return {
                "代码": code, "名称": name,
                "最新价": round(price, 2) if price else 0,
                "涨跌幅": round(change_pct, 2),
                "量比": round(vol_ratio, 2),
                "换手率": 0,
                "放量幅度": round(vol_expand, 2),
                "近5日均量": int(recent_5),
                "近10日均量": int(recent_10),
                "综合得分": round(score, 2),
                "建议买入价": suggested_buy,
                "目标止盈": target_profit,
                "强制止损": stop_loss,
                "推荐持仓": hold_days,
                "信号等级": signal_level,
                "仓位建议": position_advice,
            }
        except Exception as e:
            self.logger.debug(f"分析失败 [{code}]: {e}")
            return None
