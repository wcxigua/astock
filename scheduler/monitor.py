from typing import Optional, List, Callable
from datetime import datetime
from collector.realtime import RealtimeCollector
from storage.local_storage import LocalStorage
from interface.data_channel import DataChannel
from utils.logger import get_logger


class MarketMonitor:
    def __init__(self):
        self.logger = get_logger("MarketMonitor")
        self.collector = RealtimeCollector()
        self.storage = LocalStorage()
        self.data_channel = DataChannel()
        self._on_signal_callbacks: List[Callable] = []
        self.logger.info("盘中盯盘模块已初始化（预留）")
        self.logger.info("信号推送接口已预留")
        self.logger.info("定时复盘接口已预留")

    def register_signal_callback(self, callback: Callable):
        self._on_signal_callbacks.append(callback)
        self.logger.info(f"信号回调函数已注册: {callback.__name__}")

    def take_snapshot(self) -> bool:
        df = self.collector.fetch_all_market()
        if df is not None:
            self.storage.save_raw_market(df, f"盘中快照_{datetime.now().strftime('%H%M%S')}")
            self.data_channel.ingest_market_snapshot(df)
            return True
        return False

    def daily_review(self):
        self.logger.info("定时复盘功能已预留 — 待接入量能分析策略后启用")
        pass

    def push_signal(self, signal: dict):
        self.logger.info(f"信号推送: {signal}")
        for cb in self._on_signal_callbacks:
            try:
                cb(signal)
            except Exception as e:
                self.logger.error(f"信号回调执行失败: {e}")
