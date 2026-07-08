from typing import Dict, Optional
import pandas as pd
from collector.realtime import RealtimeCollector
from utils.logger import get_logger


class RiskController:
    def __init__(self):
        self.logger = get_logger("RiskControl")
        self.realtime = RealtimeCollector()

    def assess_market(self, market_df: pd.DataFrame = None) -> Dict:
        if market_df is None or market_df.empty:
            market_df = self.realtime.fetch_all_market()

        result = {
            "风险等级": "低",
            "总股票数": 0,
            "放量上涨家数": 0,
            "缩量下跌家数": 0,
            "上涨家数": 0,
            "下跌家数": 0,
            "平均量比": 0,
            "选股收紧": False,
            "异常换手家数": 0,
            "说明": "",
            "高风险标的": 0,
        }

        if market_df is None or market_df.empty:
            return result

        df = market_df.copy()
        result["总股票数"] = len(df)

        if "涨跌幅" not in df.columns and "最新价" in df.columns and "昨收" in df.columns:
            yc = df["昨收"].astype(float).replace(0, float("nan"))
            df["涨跌幅"] = ((df["最新价"].astype(float) - yc) / yc * 100).fillna(0)
        if "涨跌幅" in df.columns:
            result["上涨家数"] = int((df["涨跌幅"] > 0).sum())
            result["下跌家数"] = int((df["涨跌幅"] < 0).sum())

        if "换手率" in df.columns:
            high_turnover = (df["换手率"].astype(float) > 30).sum()
            result["异常换手家数"] = int(high_turnover)
            result["高风险标的"] = int((df["换手率"].astype(float) > 30).sum())

        up_pct = result["上涨家数"] / max(result["总股票数"], 1)
        high_turnover_ratio = result["异常换手家数"] / max(result["总股票数"], 1)

        if up_pct < 0.3 or high_turnover_ratio > 0.1:
            result["风险等级"] = "高"
            result["选股收紧"] = True
            result["说明"] = "大盘环境偏弱，自动收紧选股条件"
        elif up_pct < 0.45:
            result["风险等级"] = "中"
            result["选股收紧"] = True
            result["说明"] = "市场分化明显，适当收紧量能条件"
        else:
            result["风险等级"] = "低"
            result["说明"] = "市场环境良好，正常选股"

        self.logger.info(
            f"市场风险评估: 等级={result['风险等级']}, "
            f"上涨={result['上涨家数']}/{result['下跌家数']}, "
            f"高换手={result['异常换手家数']}"
        )
        return result

    def adjust_thresholds(self, risk_level: str) -> Dict:
        thresholds = {
            "低": {"量比下限": 1.8, "放量幅度下限": 50, "max_stocks": 20},
            "中": {"量比下限": 2.2, "放量幅度下限": 80, "max_stocks": 12},
            "高": {"量比下限": 3.0, "放量幅度下限": 120, "max_stocks": 5},
        }
        return thresholds.get(risk_level, thresholds["低"])
