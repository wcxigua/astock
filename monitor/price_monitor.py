import json
import os
import threading
import time
from datetime import datetime, date as dt_date
from pathlib import Path
from typing import Optional

import requests

from config.settings import DATA_DIR
from utils.logger import get_logger

logger = get_logger("PriceMonitor")

MONITOR_FILE = DATA_DIR / "monitor_list.json"


class PriceMonitor:
    TRIGGER_RANGE = 0.05

    def __init__(self):
        self._stocks: dict = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._load()

    def _load(self):
        if MONITOR_FILE.exists():
            try:
                self._stocks = json.loads(MONITOR_FILE.read_text(encoding="utf-8"))
                logger.info(f"已加载监控列表：{len(self._stocks)} 只股票")
            except Exception as e:
                logger.error(f"加载监控列表失败: {e}")
                self._stocks = {}

    def _save(self):
        MONITOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            MONITOR_FILE.write_text(json.dumps(self._stocks, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"保存监控列表失败: {e}")

    def add_stocks(self, results: list):
        if not results:
            return
        now = datetime.now()
        count = 0
        for s in results[:20]:
            code = s.get("代码", "")
            if not code:
                continue
            name = s.get("名称", "")
            buy = s.get("建议买入价")
            target = s.get("目标止盈")
            stop = s.get("强制止损")
            if not any([buy, target, stop]):
                continue
            old = self._stocks.get(code, {})
            alerts = old.get("alerts_fired", {"buy": False, "target": False, "stop": False})
            self._stocks[code] = {
                "name": name,
                "buy_price": buy,
                "target_price": target,
                "stop_price": stop,
                "updated_at": now.strftime("%m-%d %H:%M"),
                "alerts_fired": alerts,
            }
            count += 1
        self._save()
        logger.info(f"监控列表已更新：新增/更新 {count} 只股票")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        count = len(self._stocks)
        logger.info(f"价格触发监控已启动（交易时段每60秒检查一次），当前监控 {count} 只股票")

    def stop(self):
        self._running = False

    def _is_trading_time(self) -> bool:
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        hour, minute = now.hour, now.minute
        time_num = hour * 100 + minute
        if 930 <= time_num <= 1130:
            return True
        if 1300 <= time_num <= 1500:
            return True
        return False

    def _fetch_prices(self, codes: list) -> dict:
        result = {}
        try:
            tx_codes = []
            for c in codes:
                c = c.strip().lower()
                if c.startswith(("sh", "sz", "bj")):
                    tx_codes.append(c)
                elif c[0] in ("5", "6", "9"):
                    tx_codes.append(f"sh{c}")
                elif c[0] in ("0", "3"):
                    tx_codes.append(f"sz{c}")
                elif c[0] in ("4", "8"):
                    tx_codes.append(f"bj{c}")
                else:
                    tx_codes.append(f"sz{c}")
            url = f"https://qt.gtimg.cn/q={','.join(tx_codes)}"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            for line in resp.text.strip().split("\n"):
                if "=" not in line:
                    continue
                raw = line.split("=", 1)[1].strip().strip('"').strip(";").strip('"')
                fields = raw.split("~")
                if len(fields) < 40:
                    continue
                code = fields[2]
                price_str = fields[3]
                name = fields[1]
                try:
                    price = float(price_str) if price_str else 0.0
                except ValueError:
                    price = 0.0
                result[code] = {"price": price, "name": name}
        except Exception as e:
            logger.error(f"批量获取行情失败: {e}")
        return result

    def _send_alert(self, code: str, name: str, current_price: float,
                    trigger_type: str, trigger_price: float, action: str):
        webhook = os.environ.get("WECHAT_WEBHOOK", "")
        if not webhook:
            logger.warning(f"[{code}] 跳过提醒：未配置 WECHAT_WEBHOOK")
            return
        now_str = datetime.now().strftime("%H:%M")
        text = (
            f"### 【价格触发推送】{name}（{code}）\n\n"
            f"当前价：**{current_price:.2f}**\n"
            f"触发条件：接近{trigger_type}（{trigger_price:.2f}）\n"
            f"操作建议：{action}\n\n"
            f"更新时间：{now_str}"
        )
        try:
            resp = requests.post(webhook, json={
                "msgtype": "markdown",
                "markdown": {
                    "title": f"【价格触发推送】{name}({code}) {now_str}",
                    "text": text,
                },
            }, timeout=10)
            if resp.status_code == 200 and resp.json().get("errcode") == 0:
                logger.info(f"[{code}] {trigger_type}提醒发送成功（当前价{current_price:.2f}）")
            else:
                logger.error(f"[{code}] 提醒发送失败: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"[{code}] 提醒发送异常: {e}")

    def _check_prices(self):
        if not self._stocks:
            return
        codes = list(self._stocks.keys())
        prices = self._fetch_prices(codes)
        now = datetime.now()
        today = now.date()
        changed = False
        for code, info in self._stocks.items():
            if code not in prices:
                continue
            current_price = prices[code]["price"]
            if current_price <= 0:
                continue
            name = info.get("name", code)
            alerts = info.get("alerts_fired", {})
            buy_price = info.get("buy_price")
            target_price = info.get("target_price")
            stop_price = info.get("stop_price")
            if buy_price and not alerts.get("buy"):
                if abs(current_price - buy_price) <= self.TRIGGER_RANGE:
                    diff = current_price - buy_price
                    if diff >= 0:
                        action = "已到买入区间，可以考虑建仓"
                    else:
                        action = "已接近买入价，关注反弹机会"
                    self._send_alert(code, name, current_price, "计划买入价", buy_price, action)
                    alerts["buy"] = True
                    changed = True
            if target_price and not alerts.get("target"):
                if abs(current_price - target_price) <= self.TRIGGER_RANGE:
                    diff = current_price - target_price
                    if diff >= 0:
                        action = "已达标，可以考虑止盈卖出"
                    else:
                        action = "接近止盈位，做好卖出准备"
                    self._send_alert(code, name, current_price, "止盈价", target_price, action)
                    alerts["target"] = True
                    changed = True
            if stop_price and not alerts.get("stop"):
                if current_price <= stop_price + self.TRIGGER_RANGE:
                    action = "已触及止损区间，建议果断离场"
                    self._send_alert(code, name, current_price, "止损价", stop_price, action)
                    alerts["stop"] = True
                    changed = True
            if changed:
                self._stocks[code]["alerts_fired"] = alerts
        if changed:
            self._save()

    def _run_loop(self):
        while self._running:
            try:
                if self._is_trading_time() and self._stocks:
                    self._check_prices()
            except Exception as e:
                logger.error(f"价格检查异常: {e}")
            time.sleep(60)
