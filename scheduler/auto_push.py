import os
import threading
import time
from datetime import datetime, date as dt_date, time as dt_time
from typing import Optional

import requests

from collector.realtime import RealtimeCollector
from selector.volume_selector import VolumeSelector
from signals.risk_control import RiskController
from utils.ai_quota import ai_quota
from utils.logger import get_logger

logger = get_logger("AutoPush")


class AutoPusher:
    SCHEDULES = [
        ("早盘信号", dt_time(9, 25)),
        ("午盘信号", dt_time(11, 30)),
        ("收盘信号", dt_time(15, 10)),
    ]

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._done_today: set = set()
        self._realtime = RealtimeCollector()
        self._selector = VolumeSelector()
        self._risk = RiskController()
        self._market_cache = {"df": None, "time": None}

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        schedule_str = " / ".join(f"{n} {t.strftime('%H:%M')}" for n, t in self.SCHEDULES)
        logger.info(f"定时自动推送已启动：{schedule_str}")

    def stop(self):
        self._running = False

    def _refresh_market(self):
        try:
            df = self._realtime.fetch_all_market()
            if df is not None and not df.empty:
                self._market_cache["df"] = df
                self._market_cache["time"] = datetime.now()
        except Exception as e:
            logger.error(f"自动推送行情刷新失败: {e}")

    def _get_market_cache(self):
        cache = self._market_cache
        now = datetime.now()
        if cache["df"] is not None and cache["time"] and (now - cache["time"]).seconds < 60:
            return cache["df"]
        self._refresh_market()
        for _ in range(30):
            if cache["df"] is not None:
                return cache["df"]
            time.sleep(0.5)
        return cache["df"]

    def _fetch_ai_analysis(self, results, max_count=5):
        if not ai_quota.can_call():
            logger.info(f"AI配额已用完（今日上限3次），跳过AI研判")
            return {}
        ai_map = {}
        try:
            from interface.deepseek_api import DeepSeekClient
            from concurrent.futures import ThreadPoolExecutor, as_completed
            ds = DeepSeekClient()
            if ds.is_ready():
                targets = results[:max_count]
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
        return ai_map

    def _do_push(self, slot_name: str):
        webhook = os.environ.get("WECHAT_WEBHOOK", "")
        if not webhook:
            logger.warning(f"[{slot_name}] 跳过推送：未配置 WECHAT_WEBHOOK")
            return

        df = self._get_market_cache()
        if df is None or df.empty:
            logger.warning(f"[{slot_name}] 跳过推送：行情数据未就绪")
            return

        results = self._selector.screen(df)
        if not results:
            logger.warning(f"[{slot_name}] 跳过推送：暂无选股结果")
            return

        assessment = self._risk.assess_market(df)
        ai_map = self._fetch_ai_analysis(results)

        from webapp import _build_push_markdown
        markdown = _build_push_markdown(results, assessment, ai_map)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        try:
            resp = requests.post(webhook, json={
                "msgtype": "markdown",
                "markdown": {
                    "title": f"【A股超短线量能信号推送】{slot_name} {now_str}",
                    "text": markdown,
                },
            }, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("errcode") == 0:
                    logger.info(f"[{slot_name}] 推送成功，共 {len(results)} 只股票")
                else:
                    logger.error(f"[{slot_name}] 推送失败：{data.get('errmsg', '未知错误')}")
            else:
                logger.error(f"[{slot_name}] 推送失败：HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"[{slot_name}] 推送异常：{e}")

    def _run_loop(self):
        while self._running:
            now = datetime.now()
            today = now.date()
            self._done_today = {k for k in self._done_today if k[0] == today}
            for name, t in self.SCHEDULES:
                key = (today, name)
                if key not in self._done_today:
                    if now.hour == t.hour and now.minute == t.minute:
                        self._done_today.add(key)
                        logger.info(f"触发定时推送：{name}")
                        try:
                            self._do_push(name)
                        except Exception as e:
                            logger.error(f"[{name}] 推送执行异常: {e}")
            time.sleep(30)
