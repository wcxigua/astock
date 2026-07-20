#!/usr/bin/env python3
"""Standalone script: run selector → generate _site/index.html + DingTalk push"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
def now_cst():
    return datetime.now(timezone(timedelta(hours=8)))
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from collector.realtime import RealtimeCollector
from selector.volume_selector import VolumeSelector
from signals.risk_control import RiskController
from signals.trading_signal import TradingSignal
from utils.logger import get_logger
from utils.ai_quota import ai_quota

logger = get_logger("GHReport")

OUTPUT = ROOT / "_site"
OUTPUT.mkdir(exist_ok=True)

def to_dict(df):
    if df is None or df.empty:
        return []
    return json.loads(df.to_json(orient="records", force_ascii=False))

def run():
    logger.info("初始化组件...")
    realtime = RealtimeCollector()
    selector = VolumeSelector()
    risk_control = RiskController()
    trading_signal = TradingSignal()

    logger.info(f"当前北京时间: {now_cst().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("获取实时行情...")
    df = realtime.fetch_all_market()
    if df is None or df.empty:
        logger.error("行情获取失败")
        return 1

    snapshot_time = now_cst().strftime("%H:%M:%S")
    snapshot = to_dict(df)[:200]
    numeric = df.select_dtypes(include="number")
    stats = {
        "total": len(df),
        "avg_volume": round(float(numeric.get("成交量", pd.Series([0])).mean()), 2),
        "max_volume": round(float(numeric.get("成交量", pd.Series([0])).max()), 2),
        "change_up": int((df["涨跌幅"] > 0).sum()) if "涨跌幅" in df.columns else 0,
        "change_down": int((df["涨跌幅"] < 0).sum()) if "涨跌幅" in df.columns else 0,
    }

    vol_col = "成交量"
    vol_top = to_dict(df.nlargest(30, vol_col)) if vol_col in df.columns else to_dict(df.head(30))

    logger.info("执行量能选股...")
    selector_results = selector.screen(df)
    selector_top20 = selector_results[:20]

    logger.info("评估市场风险...")
    assessment = risk_control.assess_market(df)
    thresholds = risk_control.adjust_thresholds(assessment.get("风险等级", "中"))

    logger.info("生成 _site/index.html ...")
    html_template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    embedded = {
        "snapshot": {"ok": True, "total": len(snapshot), "time": snapshot_time, "data": snapshot},
        "stats": {"ok": True, "stats": stats},
        "volume": {"ok": True, "data": vol_top},
        "selector": {"ok": True, "total": len(selector_results), "data": selector_top20},
        "risk": {"ok": True, "assessment": assessment, "thresholds": thresholds},
    }
    embedded_json = json.dumps(embedded, ensure_ascii=False)

    static_script = """<script id="embedded-data" type="application/json">""" + embedded_json + """</script>"""

    html = html_template.replace("</head>", static_script + "\n</head>")
    html = html.replace(
        "loadMarket();",
        "if (window.__loadEmbedded) window.__loadEmbedded(); else loadMarket();"
    )

    (OUTPUT / "index.html").write_text(html, encoding="utf-8")
    logger.info(f"_site/index.html 已生成 ({len(embedded_json)//1024}KB 数据)")

    skip_push = os.environ.get("GITHUB_EVENT_NAME") == "push"
    try:
        webhook = os.environ.get("WECHAT_WEBHOOK", "") if not skip_push else ""
        if webhook:
            dt_str = now_cst().strftime("%Y-%m-%d %H:%M:%S")
            lines = [
                f"## 【A股超短线量能信号推送】{dt_str}",
                f"> 周期：超短线1-5日",
                "",
            ]
            rl = assessment.get("风险等级", "-")
            up = assessment.get("上涨家数", "-")
            dn = assessment.get("下跌家数", "-")
            lines.append("### 📈 大盘环境")
            lines.append(f"- 风险等级：**{rl}**")
            lines.append(f"- 上涨 {up} 家 ｜ 下跌 {dn} 家")
            lines.append("")

            ai_map = {}
            if ai_quota.can_call():
                from interface.deepseek_api import DeepSeekClient
                from concurrent.futures import ThreadPoolExecutor, as_completed
                ds = DeepSeekClient()
                if ds.is_ready():
                    targets = selector_results[:5]
                    with ThreadPoolExecutor(max_workers=3) as ex:
                        fut_map = {ex.submit(ds.analyze_stock_volume, s): s for s in targets}
                        for fut in as_completed(fut_map):
                            s = fut_map[fut]
                            try:
                                comment = fut.result(timeout=15)
                                if comment:
                                    ai_map[s["代码"]] = comment
                            except Exception:
                                pass
                    ai_quota.record_call()

            lines.append(f"### 🔍 量能强势股（共 {len(selector_results)} 只入选）")
            for i, s in enumerate(selector_top20[:10], 1):
                name = s.get("名称", "")
                code = s.get("代码", "")
                price = s.get("最新价", "-")
                chg = s.get("涨跌幅", 0)
                chg_str = f"+{chg:.2f}%" if chg and chg > 0 else f"{chg:.2f}%" if chg else "-"
                vr = s.get("量比", "-")
                ve = s.get("放量幅度", "-")
                level = s.get("信号等级", "-")
                pos = s.get("仓位建议", "-")
                buy = s.get("建议买入价", "-")
                target = s.get("目标止盈", "-")
                stop = s.get("强制止损", "-")
                lines.append(f"**{i}. {name}（{code}）**")
                lines.append(f"> 价格：{price} ｜ 涨跌：{chg_str}")
                lines.append(f"> 量比：{vr} ｜ 放量：{ve}% ｜ 信号：{level} ｜ 仓位：{pos}")
                lines.append(f"> 买入：{buy} ｜ 止盈：{target} ｜ 止损：{stop}")
                if ai_map and code in ai_map:
                    ai_comment = ai_map[code]
                    if ai_comment and ai_comment not in ("分析超时或失败", "DeepSeek API Key 未配置"):
                        lines.append(f"> AI研判：{ai_comment}")
                lines.append("")
            lines.append("---")
            lines.append(f"共 {len(selector_results)} 只股票满足量能选股条件，详情请查看系统网页")

            markdown_text = "\n".join(lines)
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"【A股超短线量能信号推送】{dt_str}",
                    "text": markdown_text,
                },
            }
            resp = requests.post(webhook, json=payload, timeout=15)
            if resp.status_code == 200 and resp.json().get("errcode") == 0:
                logger.info("钉钉推送成功")
            else:
                logger.warning(f"钉钉推送返回异常: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"推送异常: {e}")

    logger.info("完成")
    return 0

if __name__ == "__main__":
    sys.exit(run())
