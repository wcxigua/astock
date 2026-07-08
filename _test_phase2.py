import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from webapp import selector, trading_signal, risk_control, _get_market

t0 = time.time()
df = _get_market()
print(f"行情加载: {time.time()-t0:.1f}s, {len(df) if df is not None else 0} 只")

t0 = time.time()
results = selector.screen(df)
print(f"选股: {time.time()-t0:.1f}s, 命中: {len(results)} 只")
for r in results[:3]:
    print(f"  {r['代码']} {r['名称']} 量比={r['量比']} 放量={r['放量幅度']}% 得分={r['综合得分']}")

if results:
    code = results[0]["代码"]
    t0 = time.time()
    sig = trading_signal.calculate(code)
    print(f"信号({code}): {time.time()-t0:.2f}s")
    print(f"  {sig['名称']}: 买点={sig['买点区间']}, 止盈={sig['目标止盈']}, 止损={sig['强制止损']}, 持仓={sig['推荐持仓']}")

risk = risk_control.assess_market(df)
print(f"风控: 等级={risk['风险等级']}, 收紧={risk['选股收紧']}")
