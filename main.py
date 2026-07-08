from collector.realtime import RealtimeCollector
from collector.history import HistoryCollector
from storage.local_storage import LocalStorage
from interface.deepseek_api import DeepSeekClient
from interface.data_channel import DataChannel
from scheduler.workbuddy import WorkBuddyInterface
from scheduler.monitor import MarketMonitor
from utils.logger import get_logger


logger = get_logger("Main")


def main():
    logger.info("=" * 50)
    logger.info("A股量能超短线交易系统 启动")
    logger.info("周期定位: 超短线 (1-5日)")
    logger.info("=" * 50)

    RealtimeCollector()
    HistoryCollector()
    LocalStorage()
    deepseek = DeepSeekClient()
    DataChannel()
    WorkBuddyInterface()
    MarketMonitor()

    logger.info("--- 模块加载完成 ---")
    logger.info(f"  DeepSeek接口: {'已配置' if deepseek.is_ready() else '未配置API Key'}")
    logger.info("--- 系统就绪，等待指令 ---")


if __name__ == "__main__":
    main()

    rc = RealtimeCollector()
    hc = HistoryCollector()
    storage = LocalStorage()

    print("\n指令: [1]全市场快照 [2]个股行情 [3]历史量价 [q]退出")
    while True:
        try:
            cmd = input("\n>>> ").strip()
            if cmd == "q":
                break
            elif cmd == "1":
                df = rc.fetch_all_market()
                if df is not None:
                    print(f"\n全市场 {len(df)} 只股票")
                    print(df[["代码", "名称", "最新价", "成交量", "外盘", "内盘"]].head(10).to_string(index=False))
                    storage.save_raw_market(df)
            elif cmd == "2":
                code = input("输入股票代码(如 sh600519): ").strip()
                q = rc.fetch_single_quote(code)
                if q:
                    print(f"\n{q.get('名称')} ({q.get('代码')})")
                    print(f"  最新价: {q.get('最新价')}  成交量: {q.get('成交量')}")
                    print(f"  外盘: {q.get('外盘')}  内盘: {q.get('内盘')}")
            elif cmd == "3":
                code = input("输入股票代码(如 sh600519): ").strip()
                df = hc.fetch_daily_kline(code, days=30)
                if df is not None:
                    print(f"\n{code} 近30日量价数据:")
                    print(df.to_string(index=False))
                    storage.save_daily_history(df, code)
            else:
                print("指令: [1]全市场快照 [2]个股行情 [3]历史量价 [q]退出")
        except KeyboardInterrupt:
            print()
            break
        except Exception as e:
            print(f"错误: {e}")
