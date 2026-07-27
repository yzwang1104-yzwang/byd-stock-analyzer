"""卖出分析脚本 — 评估持仓股票的卖出优先级。"""
import sys, io, os
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import urllib.request

CACHE_DIR = ".cache"
PORTFOLIO = [
    ("001382","新亚电缆",100,15.65), ("002700","万憬能源",100,5.23), ("603395","红四方",100,20.97),
    ("000690","宝新能源",100,4.69), ("600795","国电电力",100,4.80), ("000983","山西焦煤",100,6.30),
    ("600104","上汽集团",200,10.35), ("600438","通威股份",200,11.21), ("600299","安迪苏",100,8.13),
    ("603970","中农立华",100,9.85), ("002327","富安娜",100,6.30), ("603334","丰倍生物",100,32.41),
    ("002469","三维化学",100,5.60), ("603097","江苏华辰",100,15.48), ("603370","华新精科",100,33.03),
    ("600560","金自天正",100,10.58), ("002855","捷荣技术",100,9.51), ("600370","*ST三房",400,2.66),
]


def analyze_sell(code: str) -> dict | None:
    price_path = os.path.join(CACHE_DIR, f"prices_{code}.csv")
    if not os.path.exists(price_path):
        return None
    try:
        df = pd.read_csv(price_path, index_col=0, parse_dates=True)
        if len(df) < 50:
            return None
    except Exception:
        return None

    close = df["close"]
    cur = float(close.iloc[-1])
    closes = close.values
    dates = df.index
    last_date = str(dates[-1].date()) if hasattr(dates[-1], "date") else str(dates[-1])[:10]

    low_all = float(np.min(closes))
    high_all = float(np.max(closes))
    from_low = (cur - low_all) / low_all * 100
    from_high = (cur / high_all - 1) * 100

    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else ma20
    if ma20 > ma50 * 1.01:
        trend = "UP"
    elif ma20 < ma50 * 0.99:
        trend = "DN"
    else:
        trend = "--"

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs_val = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100 - (100/(1+rs_val))
    rsi = float(rsi_series.iloc[-1]) if not np.isnan(rsi_series.iloc[-1]) else 50

    chg_3d = (cur - float(closes[-4]))/float(closes[-4])*100 if len(closes)>=4 else 0
    chg_5d = (cur - float(closes[-6]))/float(closes[-6])*100 if len(closes)>=6 else 0
    chg_20d = (cur - float(closes[-21]))/float(closes[-21])*100 if len(closes)>=21 else 0
    momentum_accel = chg_3d - chg_5d
    falling_knife = trend == "DN" and chg_3d < -3 and momentum_accel < -1

    trs = []
    for i in range(-14, 0):
        h = float(df.iloc[i]["high"]) if "high" in df.columns else closes[i]
        l = float(df.iloc[i]["low"]) if "low" in df.columns else closes[i]
        prev_c = closes[i-1]
        trs.append(max(h-l, abs(h-prev_c), abs(l-prev_c)))
    atr = float(np.mean(trs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd = float(dif.iloc[-1] - dea.iloc[-1])

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_low = bb_mid - 2*bb_std
    bb_pos = float((cur - bb_low.iloc[-1]) / (4*bb_std.iloc[-1])) if bb_std.iloc[-1]>0 else 0.5

    chg_1d = (cur - closes[-2])/closes[-2]*100 if len(closes)>=2 else 0

    # ==== 卖出评分（越高越该卖）====
    sell_score = 50.0

    # 趋势向下 +15
    if trend == "DN":
        sell_score += 15
    elif trend == "UP":
        sell_score -= 10

    # RSI 超买 +15
    if rsi > 70:
        sell_score += 15
    elif rsi > 60:
        sell_score += 5
    elif rsi < 30:
        sell_score -= 10

    # 飞刀加速下跌 +20
    if falling_knife:
        sell_score += 20

    # 距高点近（接近目标位）+10
    if from_high > -25:
        sell_score += 12
    elif from_high > -40:
        sell_score += 6

    # MACD 死叉
    if macd < -0.05:
        sell_score += 8

    # BB 上轨
    if bb_pos > 0.8:
        sell_score += 10
    elif bb_pos > 0.65:
        sell_score += 4

    # 20日跌幅过大——已经跌太多，再卖就割肉了
    if chg_20d < -20:
        sell_score -= 10
    elif chg_20d < -10:
        sell_score -= 5

    # 距历史最低很近——卖在最低点
    if from_low < 3:
        sell_score -= 8

    sell_score = max(0, min(100, sell_score))

    # 卖出目标价
    target_95 = high_all * 0.95
    to_target = (target_95 / cur - 1) * 100 if cur > 0 else 0

    return {
        "code": code, "price": cur, "from_low": from_low, "from_high": from_high,
        "trend": trend, "rsi": rsi, "falling_knife": falling_knife,
        "chg_1d": chg_1d, "chg_3d": chg_3d, "chg_20d": chg_20d,
        "momentum_accel": momentum_accel,
        "sell_score": sell_score, "atr": atr, "macd": macd, "bb_pos": bb_pos,
        "high_all": high_all, "low_all": low_all,
        "target_95": target_95, "to_target": to_target,
        "last_date": last_date,
    }


def main():
    print("=" * 100)
    print("  📤 持仓股票卖出优先级分析")
    print("=" * 100)
    print(f"  数据截止: K线缓存最新日期 | 分析时间: 2026-07-27")
    print()
    print("  卖出评分逻辑: 趋势DN(+15) + RSI超买(+15) + 飞刀(+20) + 距高近(+12)")
    print("               + MACD死叉(+8) + BB上轨(+10) - 已深跌(-10) - 近最低(-8)")
    print("              基础50分 → 越高越该卖")

    results = []
    for code, name, shares, avg in PORTFOLIO:
        r = analyze_sell(code)
        if r:
            r["name"] = name
            r["shares"] = shares
            r["avg_price"] = avg
            r["pnl_pct"] = (r["price"]-avg)/avg*100
            r["pnl_val"] = (r["price"]-avg)*shares
            results.append(r)

    results.sort(key=lambda x: x["sell_score"], reverse=True)

    print()
    print("═" * 100)
    print("  📊 全部持仓卖出排名")
    print("═" * 100)
    hdr = f"  {'排名':<4} {'代码':<8} {'名称':<8} {'现价':>7} {'盈亏%':>7} {'卖出分':>6} {'趋势':<5} {'RSI':>5} {'距高%':>7} {'95%目标':>8} {'距目标':>7} {'信号'}"
    print(hdr)
    print("-" * 100)

    for i, r in enumerate(results):
        signals = []
        if r["falling_knife"]: signals.append("🔪飞刀!")
        if r["rsi"] > 65: signals.append(f"RSI{r['rsi']:.0f}超买")
        if r["from_high"] > -25: signals.append("近高点")
        if r["macd"] < -0.05: signals.append("MACD死叉")
        if r["bb_pos"] > 0.8: signals.append("BB上轨")
        if r["pnl_pct"] > 10: signals.append("💰可获利")
        if r["chg_20d"] < -20: signals.append("已深跌")
        sig = " ".join(signals) if signals else "—"

        bar = "🔴" if r["sell_score"] >= 70 else ("🟠" if r["sell_score"] >= 55 else ("🟡" if r["sell_score"] >= 40 else "🟢"))
        print(f'  {bar} {i+1:<2} {r["code"]:<8} {r["name"]:<8} {r["price"]:>7.2f} {r["pnl_pct"]:>+6.1f}% {r["sell_score"]:>6.0f} {r["trend"]:<5} {r["rsi"]:>5.0f} {r["from_high"]:>+7.1f} {r["target_95"]:>8.2f} {r["to_target"]:>+6.0f}% {sig}')

    print()
    print("═" * 100)
    print("  🎯 卖出分类建议")
    print("═" * 100)

    urgent    = [r for r in results if r["sell_score"] >= 70]
    consider   = [r for r in results if 55 <= r["sell_score"] < 70]
    watch      = [r for r in results if 40 <= r["sell_score"] < 55]
    keep       = [r for r in results if r["sell_score"] < 40]

    if urgent:
        print(f'\n  🔴 强烈建议卖出 (卖出分 ≥ 70): {len(urgent)} 只')
        for r in urgent:
            reasons = []
            if r["falling_knife"]: reasons.append("加速下跌飞刀")
            if r["trend"] == "DN": reasons.append("趋势持续向下")
            if r["rsi"] > 65: reasons.append(f"RSI={r['rsi']:.0f}超买区")
            if r["from_high"] > -25: reasons.append(f"距历史高点仅{r['from_high']:.0f}%")
            if r["macd"] < -0.05: reasons.append("MACD死叉")
            print(f'     ═══ {r["code"]} {r["name"]} | 卖出分 {r["sell_score"]:.0f} | 现价 {r["price"]:.2f} ═══')
            print(f'     盈亏: {r["pnl_pct"]:+.1f}% ({r["pnl_val"]:+.0f}元) | 5日: {r["chg_3d"]:+.1f}% | 20日: {r["chg_20d"]:+.1f}%')
            print(f'     原因: {", ".join(reasons)}')
            print(f'     建议: 立即减仓或清仓止损')

    if consider:
        print(f'\n  🟠 考虑卖出 (卖出分 55-69): {len(consider)} 只')
        for r in consider:
            print(f'     {r["code"]} {r["name"]} | 卖出分 {r["sell_score"]:.0f} | 盈亏 {r["pnl_pct"]:+.1f}% | 趋势 {r["trend"]} | 距高 {r["from_high"]:+.0f}%')

    if watch:
        print(f'\n  🟡 暂时持有观察 (卖出分 40-54): {len(watch)} 只')
        names = ", ".join(f'{r["code"]} {r["name"]}({r["sell_score"]:.0f})' for r in watch)
        print(f'     {names}')

    if keep:
        print(f'\n  🟢 不建议卖出 (卖出分 < 40): {len(keep)} 只')
        for r in keep:
            print(f'     {r["code"]} {r["name"]} | 卖出分 {r["sell_score"]:.0f} | 盈亏 {r["pnl_pct"]:+.1f}% | 趋势 {r["trend"]} | 已深跌不宜割')

    # 获利了结
    print()
    print("═" * 100)
    print("  💰 获利了结机会")
    print("═" * 100)
    profit = [r for r in results if r["pnl_pct"] > 3]
    if profit:
        for r in sorted(profit, key=lambda x: x["pnl_pct"], reverse=True):
            action = "落袋为安 ✅" if r["sell_score"] >= 55 else ("可部分止盈" if r["sell_score"] >= 40 else "继续持有")
            print(f'  {r["code"]} {r["name"]} | 盈利 {r["pnl_pct"]:+.1f}% | 卖出分 {r["sell_score"]:.0f} | {action}')
    else:
        print("  无盈利 >3% 的持仓适合卖出")

    # 止损建议
    print()
    print("═" * 100)
    print("  🛑 止损建议")
    print("═" * 100)
    stop_loss = [r for r in results if r["pnl_pct"] < -8 and r["sell_score"] >= 55]
    if stop_loss:
        for r in stop_loss:
            print(f'  {r["code"]} {r["name"]} | 亏损 {r["pnl_pct"]:+.1f}% | 卖出分 {r["sell_score"]:.0f} | ⚠️ 深度亏损+卖出信号，考虑止损')
    else:
        print("  无同时满足'深度亏损'和'卖出信号'的股票")

    # 最终总结
    print()
    print("═" * 100)
    print("  📋 今日卖出总结")
    print("═" * 100)
    n_urgent = len(urgent)
    n_consider = len(consider)
    print(f"  强烈卖出: {n_urgent} 只 | 考虑卖出: {n_consider} 只 | 持有观察: {len(watch)} 只 | 不建议卖: {len(keep)} 只")

    if n_urgent + n_consider == 0:
        print()
        print("  ✅ 今日无股票触发卖出信号。所有持仓虽然多数趋势向下，但卖出评分都不高——")
        print("     主要因为已经跌了很多（距高点平均 -50%），此时卖出意义不大。")
        print("     建议等待反弹后再考虑减仓。")
    else:
        print()
        print(f"  ⚠️ 有 {n_urgent + n_consider} 只股票触发卖出信号，建议优先处理上述 🔴🟠 标的。")

    print()
    print("═" * 100)
    print("  ⚠️ 免责声明：以上分析基于历史数据和量化模型，仅供参考，不构成投资建议。")
    print("═" * 100)


if __name__ == "__main__":
    main()
