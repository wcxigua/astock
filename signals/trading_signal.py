from typing import Optional, Dict, List
from collector.realtime import RealtimeCollector
from collector.history import HistoryCollector
from utils.logger import get_logger


class TradingSignal:
    def __init__(self):
        self.logger = get_logger("TradingSignal")
        self.realtime = RealtimeCollector()
        self.history = HistoryCollector()

    def calculate(self, code: str) -> Optional[Dict]:
        try:
            quote = self.realtime.fetch_single_quote(code)
            if not quote:
                return None

            hist = self.history.fetch_daily_kline(code, days=60)
            if hist is None or hist.empty:
                return None

            price = float(quote.get("最新价", 0))
            if price <= 0:
                return None
            yc = float(quote.get("昨收", price))

            today_vol = float(quote.get("成交量", 0))

            recent_5_vol = hist.tail(5)["成交量"].mean() if len(hist) >= 5 else 0
            recent_10_vol = hist.tail(10)["成交量"].mean() if len(hist) >= 10 else 0

            recent_high = float(hist.tail(20)["最高"].max()) if len(hist) >= 20 else price
            recent_low = float(hist.tail(20)["最低"].min()) if len(hist) >= 20 else price
            avg_price_5 = float(hist.tail(5)["收盘"].mean()) if len(hist) >= 5 else price
            avg_price_10 = float(hist.tail(10)["收盘"].mean()) if len(hist) >= 10 else price
            avg_price_20 = float(hist.tail(20)["收盘"].mean()) if len(hist) >= 20 else price

            vol_ratio = today_vol / recent_5_vol if recent_5_vol > 0 else 0
            vol_expand = (recent_5_vol / recent_10_vol - 1) * 100 if recent_10_vol > 0 else 0

            price_above_ma5 = price > avg_price_5
            price_above_ma10 = price > avg_price_10
            price_above_ma20 = price > avg_price_20
            vol_price_align = price_above_ma5 and price_above_ma10
            volume_up_trend = recent_5_vol > recent_10_vol

            support = recent_low
            resistance = recent_high
            ma_support = min(avg_price_5, avg_price_10, avg_price_20)

            buy_zone_low = round(max(support, ma_support) * 1.01, 2)
            buy_zone_high = round(min(resistance * 0.98, avg_price_5 * 1.02), 2)
            if buy_zone_low > buy_zone_high:
                buy_zone_low, buy_zone_high = buy_zone_high, buy_zone_low
            suggested_buy = round((buy_zone_low + buy_zone_high) / 2, 2)

            if vol_ratio >= 2.5 and vol_expand >= 80 and vol_price_align:
                signal_level = "强信号"
                position_advice = "重仓（半仓以上）"
                target_mult = 1.10
                stop_mult = 0.93
                hold_days = "1-3日"
            elif vol_ratio >= 1.8 and vol_expand >= 50 and vol_price_align:
                signal_level = "中信号"
                position_advice = "半仓"
                target_mult = 1.08
                stop_mult = 0.95
                hold_days = "2-4日"
            elif vol_ratio >= 1.3 or (vol_expand >= 30 and volume_up_trend):
                signal_level = "弱信号"
                position_advice = "轻仓（注意风险）"
                target_mult = 1.05
                stop_mult = 0.97
                hold_days = "3-5日"
            else:
                signal_level = "弱信号"
                position_advice = "轻仓（注意风险）"
                target_mult = 1.03
                stop_mult = 0.98
                hold_days = "3-5日"

            target_profit = round(price * target_mult, 2)
            stop_loss = round(max(support * stop_mult, price * 0.93), 2)
            stop_loss = min(stop_loss, round(price * 0.97, 2))

            return {
                "代码": code,
                "名称": quote.get("名称", ""),
                "最新价": round(price, 2),
                "涨跌幅": round(((price - yc) / yc) * 100, 2) if yc > 0 else 0,
                "买点区间": f"{buy_zone_low} - {buy_zone_high}",
                "买入低位": buy_zone_low,
                "买入高位": buy_zone_high,
                "建议买入价": suggested_buy,
                "目标止盈": target_profit,
                "止盈涨幅": round((target_profit / price - 1) * 100, 2),
                "强制止损": stop_loss,
                "止损跌幅": round((1 - stop_loss / price) * 100, 2),
                "推荐持仓": hold_days,
                "信号等级": signal_level,
                "仓位建议": position_advice,
                "量比": round(vol_ratio, 2),
                "放量幅度": round(vol_expand, 2),
                "近5日均价": round(avg_price_5, 2),
                "近10日均价": round(avg_price_10, 2),
                "近20日均价": round(avg_price_20, 2),
                "近20日支撑": round(support, 2),
                "近20日压力": round(resistance, 2),
                "量价匹配": "是" if vol_price_align else "否",
                "量能趋势": "放量" if volume_up_trend else "缩量",
                "价在5日线上": "是" if price_above_ma5 else "否",
            }
        except Exception as e:
            self.logger.error(f"信号计算失败 [{code}]: {e}")
            return None

    def batch_calculate(self, codes: List[str]) -> List[Dict]:
        results = []
        for code in codes:
            sig = self.calculate(code)
            if sig:
                results.append(sig)
        results.sort(key=lambda x: x.get("量比", 0), reverse=True)
        return results
