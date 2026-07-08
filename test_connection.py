import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from collector.realtime import RealtimeCollector
from collector.history import HistoryCollector
from storage.local_storage import LocalStorage
from utils.logger import get_logger
import traceback

logger = get_logger("DataDebug")

def test_realtime_market():
    print("\n>>> [测试1] 全市场实时行情 (腾讯批量API)")
    collector = RealtimeCollector()
    df = collector.fetch_all_market()
    if df is not None and not df.empty:
        print(f"  全市场股票数量: {len(df)}")
        print(f"  数据列: {list(df.columns)}")
        volume_cols = [c for c in df.columns if "量" in str(c) or "换手" in str(c)]
        print(f"  量能相关字段: {volume_cols}")
        print(f"  前3条预览:\n{df.head(3).to_string(index=False)}\n")
        return True
    print("  x 失败: 返回空\n")
    return False

def test_tencent_quote():
    print(">>> [测试2] 腾讯个股实时行情 (例: sh600519)")
    collector = RealtimeCollector()
    quote = collector.fetch_single_quote("sh600519")
    if quote:
        print(f"  名称={quote.get('名称')}, 最新价={quote.get('最新价')}")
        print(f"  成交量={quote.get('成交量')}, 内盘={quote.get('内盘')}, 外盘={quote.get('外盘')}")
    else:
        print("  - 获取失败")
    inner_outer = collector.fetch_inner_outer_volume("sh600519")
    if inner_outer:
        print(f"  内外盘: {inner_outer}\n")
    return True

def test_history_data():
    print(">>> [测试3] 个股日线历史量价数据 (例: sh600519, 90天)")
    collector = HistoryCollector()
    df = collector.fetch_daily_kline("sh600519", days=90)
    if df is not None and not df.empty:
        print(f"  数据条数: {len(df)}")
        print(f"  数据列: {list(df.columns)}")
        print(f"  最新5条:\n{df.tail(5).to_string(index=False)}\n")
        return True
    print("  x 失败\n")
    return False

def test_storage():
    print(">>> [测试4] 本地数据存储")
    collector = RealtimeCollector()
    storage = LocalStorage()
    df = collector.fetch_all_market()
    if df is not None and not df.empty:
        ok = storage.save_raw_market(df, "调试测试")
        print(f"  全市场数据保存: {'OK' if ok else 'FAIL'}")
        loaded = storage.load_market_snapshot("调试测试")
        if loaded is not None:
            print(f"  读取验证: {len(loaded)} 条\n")
        return True
    return False

def test_deepseek_config():
    print(">>> [测试5] DeepSeek 接口状态")
    from interface.deepseek_api import DeepSeekClient
    client = DeepSeekClient()
    print(f"  DeepSeek: {'OK - 已配置' if client.is_ready() else '- API Key 未配置'}\n")
    return True

def test_data_channel():
    print(">>> [测试6] 数据通道测试")
    from interface.data_channel import DataChannel
    channel = DataChannel()
    collector = RealtimeCollector()
    df = collector.fetch_all_market()
    if df is not None and not df.empty:
        channel.ingest_market_snapshot(df)
        model_input = channel.build_model_input(top_n=5)
        if model_input:
            print(f"  行情快照已摄入: OK")
            print(f"  Model Input 构建成功: {len(model_input.get('market_overview', {}).get('top_volume_stocks', []))} 只\n")
        return True
    return False

def main():
    print("=" * 60)
    print("  A股量能超短线交易系统 - 数据接口调试")
    print("=" * 60)
    results = []
    tests = [
        ("全市场实时行情", test_realtime_market),
        ("腾讯个股行情", test_tencent_quote),
        ("历史量价数据", test_history_data),
        ("本地存储", test_storage),
        ("DeepSeek配置", test_deepseek_config),
        ("数据通道", test_data_channel),
    ]
    import time
    for name, func in tests:
        try:
            results.append((name, func()))
            if "深Seek" not in name and "存储" not in name:
                time.sleep(1)
        except Exception as e:
            print(f"  x [{name}] 异常: {e}")
            traceback.print_exc()
            results.append((name, False))
    print("=" * 60)
    print("  测试结果汇总:")
    for name, ok in results:
        print(f"    [{'OK' if ok else 'FAIL'}] {name}")
    print("=" * 60)

if __name__ == "__main__":
    main()
