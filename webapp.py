import csv
import io
import json
import os
import threading
import time
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
from flask import Flask, render_template, jsonify, request

from collector.realtime import RealtimeCollector
from collector.history import HistoryCollector
from selector.volume_selector import VolumeSelector
from signals.trading_signal import TradingSignal
from signals.risk_control import RiskController
from scheduler.auto_push import AutoPusher
from monitor.price_monitor import PriceMonitor
from utils.ai_quota import ai_quota
from utils.logger import get_logger

app = Flask(__name__)
logger = get_logger("WebApp")

realtime = RealtimeCollector()
history = HistoryCollector()
selector = VolumeSelector()
trading_signal = TradingSignal()
risk_control = RiskController()
price_monitor = PriceMonitor()

_market_cache = {"df": None, "time": None, "loading": False}


def _to_dict(df):
    if df is None or df.empty:
        return []
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _refresh_cache():
    if _market_cache["loading"]:
        return
    _market_cache["loading"] = True
    try:
        df = realtime.fetch_all_market()
        if df is not None and not df.empty:
            _market_cache["df"] = df
            _market_cache["time"] = datetime.now()
            logger.info(f"行情缓存已刷新: {len(df)} 只")
    except Exception as e:
        logger.error(f"缓存刷新失败: {e}")
    finally:
        _market_cache["loading"] = False


def _get_market():
    cache = _market_cache
    now = datetime.now()
    if cache["df"] is not None and cache["time"] and (now - cache["time"]).seconds < 30:
        return cache["df"]
    if not cache["loading"]:
        _refresh_cache()
    for _ in range(60):
        if cache["df"] is not None:
            return cache["df"]
        time.sleep(0.5)
    return cache["df"]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/market/snapshot")
def api_market_snapshot():
    df = _get_market()
    if df is None or df.empty:
        return jsonify({"ok": False, "msg": "行情加载中，请稍候..."})
    data = _to_dict(df)
    return jsonify({
        "ok": True, "total": len(data),
        "time": (_market_cache["time"] or datetime.now()).strftime("%H:%M:%S"),
        "data": data[:200],
    })


@app.route("/api/market/stats")
def api_market_stats():
    df = _get_market()
    if df is None or df.empty:
        return jsonify({"ok": False})
    numeric = df.select_dtypes(include="number")
    stats = {
        "total": len(df),
        "avg_volume": round(float(numeric.get("成交量", pd.Series([0])).mean()), 2) if "成交量" in numeric else 0,
        "max_volume": round(float(numeric.get("成交量", pd.Series([0])).max()), 2) if "成交量" in numeric else 0,
        "change_up": len(df[df["涨跌幅"] > 0]) if "涨跌幅" in df.columns else 0,
        "change_down": len(df[df["涨跌幅"] < 0]) if "涨跌幅" in df.columns else 0,
    }
    return jsonify({"ok": True, "stats": stats})


@app.route("/api/stock/<symbol>")
def api_stock_detail(symbol: str):
    quote = realtime.fetch_single_quote(symbol)
    hist = history.fetch_daily_kline(symbol, days=60)
    return jsonify({"ok": True, "quote": quote, "history": _to_dict(hist)})


@app.route("/api/stock/<symbol>/history")
def api_stock_history(symbol: str):
    days = request.args.get("days", 90, type=int)
    df = history.fetch_daily_kline(symbol, days=days)
    if df is None or df.empty:
        return jsonify({"ok": False})
    return jsonify({"ok": True, "data": _to_dict(df)})


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip().upper()
    df = _get_market()
    if df is None or df.empty:
        return jsonify({"ok": False})
    if "代码" in df.columns:
        mask = df["代码"].astype(str).str.contains(q, na=False)
        if "名称" in df.columns:
            mask = mask | df["名称"].str.contains(q, na=False)
        result = df[mask].head(20)
        return jsonify({"ok": True, "data": _to_dict(result)})
    return jsonify({"ok": False})


@app.route("/api/volume/top")
def api_volume_top():
    n = request.args.get("n", 30, type=int)
    df = _get_market()
    if df is None or df.empty:
        return jsonify({"ok": False})
    vol_col = "成交量"
    if vol_col in df.columns:
        top = df.nlargest(n, vol_col)
    else:
        top = df.head(n)
    return jsonify({"ok": True, "data": _to_dict(top)})


@app.route("/api/selector/screen")
def api_selector_screen():
    df = _get_market()
    if df is None or df.empty:
        return jsonify({"ok": False, "msg": "行情数据未就绪"})
    results = selector.screen(df)
    return jsonify({"ok": True, "total": len(results), "data": results})


@app.route("/api/selector/top20")
def api_selector_top20():
    df = _get_market()
    if df is None or df.empty:
        return jsonify({"ok": False})
    results = selector.screen(df)
    return jsonify({"ok": True, "total": len(results), "data": results[:20]})


@app.route("/api/signal/calculate")
def api_signal_calculate():
    code = request.args.get("code", "").strip()
    if not code:
        return jsonify({"ok": False, "msg": "缺少股票代码"})
    result = trading_signal.calculate(code)
    if not result:
        return jsonify({"ok": False, "msg": "信号计算失败"})
    return jsonify({"ok": True, "data": result})


@app.route("/api/signal/batch")
def api_signal_batch():
    codes_str = request.args.get("codes", "")
    if not codes_str:
        df = _get_market()
        if df is None or df.empty:
            return jsonify({"ok": False})
        top = df.nlargest(30, "成交量") if "成交量" in df.columns else df.head(30)
        codes = top["代码"].tolist()
    else:
        codes = [c.strip() for c in codes_str.split(",") if c.strip()]
    results = trading_signal.batch_calculate(codes)
    return jsonify({"ok": True, "total": len(results), "data": results[:20]})


@app.route("/api/risk/assessment")
def api_risk_assessment():
    df = _get_market()
    assessment = risk_control.assess_market(df)
    thresholds = risk_control.adjust_thresholds(assessment["风险等级"])
    return jsonify({"ok": True, "assessment": assessment, "thresholds": thresholds})


@app.route("/api/selector/deepseek/analyze")
def api_deepseek_analyze():
    if not ai_quota.can_call():
        return jsonify({"ok": False, "msg": "今日AI调用额度已用完（每日上限3次），明天再来"})
    from interface.deepseek_api import DeepSeekClient
    from concurrent.futures import ThreadPoolExecutor, as_completed
    ds = DeepSeekClient()
    if not ds.is_ready():
        return jsonify({"ok": False, "msg": "DeepSeek API Key 未配置"})
    df = _get_market()
    if df is None or df.empty:
        return jsonify({"ok": False, "msg": "行情数据未就绪"})
    results = selector.screen(df)
    max_stocks = request.args.get("n", 10, type=int)
    targets = results[:max_stocks]
    analyses = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        fut_map = {ex.submit(ds.analyze_stock_volume, s): s for s in targets}
        for fut in as_completed(fut_map):
            s = fut_map[fut]
            try:
                comment = fut.result(timeout=20)
            except Exception:
                comment = None
            analyses.append({
                "代码": s["代码"],
                "名称": s["名称"],
                "AI研判备注": comment or "分析超时或失败",
            })
    analyses.sort(key=lambda x: next(i for i, s in enumerate(targets) if s["代码"] == x["代码"]))
    ai_quota.record_call()
    return jsonify({"ok": True, "total": len(analyses), "data": analyses})


@app.route("/api/selector/export")
def api_selector_export():
    df = _get_market()
    if df is None or df.empty:
        return jsonify({"ok": False, "msg": "行情数据未就绪"})
    results = selector.screen(df)
    if not results:
        return jsonify({"ok": False, "msg": "暂无选股结果"})
    field_names = ["代码", "名称", "最新价", "涨跌幅", "量比", "放量幅度",
                   "信号等级", "仓位建议", "建议买入价", "目标止盈",
                   "强制止损", "推荐持仓", "综合得分"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=field_names, extrasaction="ignore")
    writer.writeheader()
    for r in results:
        row = {k: r.get(k, "") for k in field_names}
        writer.writerow(row)
    csv_data = buf.getvalue()
    buf.close()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    response = app.response_class(
        csv_data,
        mimetype="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="selector_{timestamp}.csv"'}
    )
    return response


def _build_push_markdown(results, assessment=None, ai_map=None):
    """构建推送用的Markdown内容，包含大盘环境 + 个股信息 + AI研判"""
    from config.settings import TRADING_CYCLE
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"## 【A股超短线量能信号推送】{now_str}",
        f"> 周期：{TRADING_CYCLE}",
        "",
    ]
    if assessment:
        rl = assessment.get("风险等级", "-")
        up = assessment.get("上涨家数", "-")
        down = assessment.get("下跌家数", "-")
        abnormal = assessment.get("异常换手家数", "-")
        desc = assessment.get("说明", "")
        lines.append("### 📈 大盘环境")
        lines.append(f"- 风险等级：**{rl}**")
        lines.append(f"- 上涨 {up} 家 ｜ 下跌 {down} 家 ｜ 异常换手 {abnormal} 家")
        if desc:
            lines.append(f"- {desc}")
        lines.append("")
    top = results[:10]
    lines.append(f"### 🔍 量能强势股（共 {len(results)} 只入选）")
    lines.append("")
    for i, s in enumerate(top, 1):
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
    lines.append(f"共 {len(results)} 只股票满足量能选股条件，详情请查看系统网页")
    return "\n".join(lines)


@app.route("/api/wechat/push")
def api_wechat_push():
    webhook = os.environ.get("WECHAT_WEBHOOK", "")
    if not webhook:
        return jsonify({"ok": False, "msg": "未配置 WECHAT_WEBHOOK（钉钉/企微）环境变量"})
    df = _get_market()
    if df is None or df.empty:
        return jsonify({"ok": False, "msg": "行情数据未就绪"})
    results = selector.screen(df)
    if not results:
        return jsonify({"ok": False, "msg": "暂无选股结果"})
    assessment = risk_control.assess_market(df)
    ai_map = {}
    if ai_quota.can_call():
        try:
            from interface.deepseek_api import DeepSeekClient
            from concurrent.futures import ThreadPoolExecutor, as_completed
            ds = DeepSeekClient()
            if ds.is_ready():
                targets = results[:5]
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
        except Exception:
            pass
    markdown = _build_push_markdown(results, assessment, ai_map)
    dt_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        resp = requests.post(webhook, json={
            "msgtype": "markdown",
            "markdown": {
                "title": f"【A股超短线量能信号推送】{dt_str}",
                "text": markdown,
            },
        }, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("errcode") == 0:
                price_monitor.add_stocks(results)
                return jsonify({"ok": True, "msg": f"钉钉推送成功，共 {len(results)} 只股票"})
            else:
                return jsonify({"ok": False, "msg": f"推送失败：{data.get('errmsg', '未知错误')}"})
        else:
            return jsonify({"ok": False, "msg": f"推送失败：HTTP {resp.status_code}"})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"推送异常：{e}"})


@app.route("/api/wechat/push/serverchan")
def api_wechat_push_serverchan():
    send_key = os.environ.get("SEND_KEY", "")
    if not send_key:
        return jsonify({"ok": False, "msg": "未配置 SEND_KEY（Server酱）环境变量"})
    df = _get_market()
    if df is None or df.empty:
        return jsonify({"ok": False, "msg": "行情数据未就绪"})
    results = selector.screen(df)
    if not results:
        return jsonify({"ok": False, "msg": "暂无选股结果"})
    assessment = risk_control.assess_market(df)
    ai_map = {}
    try:
        from interface.deepseek_api import DeepSeekClient
        from concurrent.futures import ThreadPoolExecutor, as_completed
        ds = DeepSeekClient()
        if ds.is_ready():
            targets = results[:5]
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
    except Exception:
        pass
    markdown = _build_push_markdown(results, assessment, ai_map)
    try:
        resp = requests.post(
            f"https://sctapi.ftqq.com/{send_key}.send",
            json={"title": f"A股量能超短线交易信号 {datetime.now().strftime('%m-%d %H:%M')}", "desp": markdown},
            timeout=15,
        )
        data = resp.json()
        if data.get("code") == 0:
            return jsonify({"ok": True, "msg": f"Server酱推送成功，共 {len(results)} 只股票"})
        else:
            return jsonify({"ok": False, "msg": f"推送失败：{data.get('message', '未知错误')}"})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"推送异常：{e}"})


@app.route("/api/wechat/push/workweixin")
def api_wechat_push_workweixin():
    webhook = os.environ.get("WECHAT_WEBHOOK", "")
    if not webhook:
        return jsonify({"ok": False, "msg": "未配置 WECHAT_WEBHOOK 环境变量"})
    df = _get_market()
    if df is None or df.empty:
        return jsonify({"ok": False, "msg": "行情数据未就绪"})
    results = selector.screen(df)
    if not results:
        return jsonify({"ok": False, "msg": "暂无选股结果"})
    assessment = risk_control.assess_market(df)
    ai_map = {}
    try:
        from interface.deepseek_api import DeepSeekClient
        from concurrent.futures import ThreadPoolExecutor, as_completed
        ds = DeepSeekClient()
        if ds.is_ready():
            targets = results[:5]
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
    except Exception:
        pass
    markdown = _build_push_markdown(results, assessment, ai_map)
    try:
        resp = requests.post(webhook, json={
            "msgtype": "markdown",
            "markdown": {"content": markdown}
        }, timeout=10)
        if resp.status_code == 200:
            return jsonify({"ok": True, "msg": f"企业微信推送成功，共 {len(results)} 只股票"})
        else:
            return jsonify({"ok": False, "msg": f"推送失败：HTTP {resp.status_code}"})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"推送异常：{e}"})


@app.route("/api/workbuddy/reserved")
def api_workbuddy_reserved():
    return jsonify({
        "ok": True,
        "msg": "WorkBuddy定时值守接口已预留，待接入盘中盯盘/复盘/推送",
        "status": "reserved"
    })


def _prefetch_history():
    df = _market_cache.get("df")
    if df is None or df.empty:
        return
    from selector.volume_selector import VolumeSelector
    vs = VolumeSelector()
    try:
        logger.info("开始预缓存历史量价数据...")
        vs.screen(df)
        logger.info("历史量价数据预缓存完成")
    except Exception as e:
        logger.error(f"预缓存失败: {e}")


if __name__ == "__main__":
    import webbrowser
    import threading
    logger.info("预加载行情数据，请稍候...")
    _refresh_cache()
    t = threading.Thread(target=_prefetch_history, daemon=True)
    t.start()
    logger.info("启动Web界面: http://127.0.0.1:5000")
    _auto_pusher = AutoPusher()
    _auto_pusher.start()
    price_monitor.start()
    app.run(debug=False, host="127.0.0.1", port=5000)
