"""持仓分析脚本 — 分析 portfolio.txt 中所有持仓股票的明日趋势。

输出: 每只股票的评分/趋势/RSI/距低/距高/预测区间/操作建议。
数据: 缓存K线(技术指标) + 腾讯实时行情(现价/名称)
"""

import os
import ssl
import sys
import io
import urllib.request

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _fetch_realtime_batch(codes: list[str]) -> dict:
    """批量获取腾讯实时名称+价格。"""
    result = {}
    items = []
    for c in codes:
        prefix = "nq" if c.startswith(("9", "8")) else ("sz" if c.startswith(("0", "3")) else "sh")
        items.append(f"{prefix}{c}")
    try:
        url = f"https://qt.gtimg.cn/q={','.join(items)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx).read()
        for line in raw.decode("gbk", errors="replace").split("\n"):
            if "~" in line and "none_match" not in line:
                parts = line.split("~")
                if len(parts) >= 4:
                    raw_head = parts[0]
                    code_raw = ""
                    for ch in raw_head:
                        if ch.isdigit():
                            code_raw += ch
                        elif code_raw:
                            break
                    code_raw = code_raw[-6:] if len(code_raw) >= 6 else code_raw
                    name = parts[1].strip()
                    try:
                        price = float(parts[3])
                    except ValueError:
                        price = None
                    if code_raw:
                        result[code_raw] = {"name": name, "price": price}
    except Exception:
        pass
    return result
from datetime import datetime

CACHE_DIR = ".cache"
PORTFOLIO_FILE = "portfolio.txt"

def analyze_stock(code: str) -> dict | None:
    """快速分析单只股票（内联版本，避免导入链问题）。"""
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

    # 历史最低/最高
    low_all = float(np.min(closes))
    high_all = float(np.max(closes))
    from_low = (cur - low_all) / low_all * 100
    from_high = (cur / high_all - 1) * 100

    # 均线
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else ma20
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else ma50

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    rsi = float(rsi_series.iloc[-1]) if not np.isnan(rsi_series.iloc[-1]) else 50.0

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd = float(dif.iloc[-1] - dea.iloc[-1])
    macd_val = float(dif.iloc[-1])

    # ATR(14)
    trs = []
    for i in range(-14, 0):
        h = float(df.iloc[i]["high"]) if "high" in df.columns else closes[i]
        l = float(df.iloc[i]["low"]) if "low" in df.columns else closes[i]
        prev_c = closes[i - 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    atr = float(np.mean(trs))

    # 布林带
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_pos = float((cur - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1])) if bb_upper.iloc[-1] != bb_lower.iloc[-1] else 0.5

    # 涨跌幅
    chg_20d = (cur - float(closes[-21])) / float(closes[-21]) * 100 if len(closes) >= 21 else 0
    chg_10d = (cur - float(closes[-11])) / float(closes[-11]) * 100 if len(closes) >= 11 else 0
    chg_5d = (cur - float(closes[-6])) / float(closes[-6]) * 100 if len(closes) >= 6 else 0
    chg_3d = (cur - float(closes[-4])) / float(closes[-4]) * 100 if len(closes) >= 4 else 0

    # 趋势判定
    if ma20 > ma50 * 1.01:
        trend = "UP ▲"
    elif ma20 < ma50 * 0.99:
        trend = "DN ▼"
    else:
        trend = "-- →"

    # 动量
    momentum_accel = chg_3d - chg_5d

    # 飞刀检测
    falling_knife = (trend == "DN ▼") and chg_3d < -3 and momentum_accel < -1

    # 估值分位
    pe_pct = _read_valuation(code, "pe")
    pb_pct = _read_valuation(code, "pb")

    # ==== 评分 ====
    score = 50.0

    # PE 分位: 便宜加分，贵减分
    if pe_pct is not None:
        score += max(0, min(25, (1 - pe_pct / 100) * 25))
    else:
        score -= 3

    # PB 分位
    if pb_pct is not None:
        score += max(0, min(10, (1 - pb_pct / 100) * 10))

    # RSI（顺势操作）
    if trend == "UP ▲":
        if rsi < 25: score += 12
        elif rsi < 30: score += 8
        elif rsi < 35: score += 5
        elif rsi > 75: score -= 8
    elif trend == "-- →":
        if rsi < 25: score += 8
        elif rsi < 30: score += 5
        elif rsi > 75: score -= 5
    else:
        if rsi < 25 and momentum_accel > -0.5: score += 4
        elif rsi < 30 and momentum_accel > 0: score += 2
        elif rsi > 75: score -= 3

    # 趋势
    if trend == "UP ▲": score += 12
    elif trend == "-- →": score += 4
    else: score -= 6

    # MACD
    if macd > 0: score += 5
    elif macd < -0.1: score -= 3

    # 布林带
    if not falling_knife:
        if bb_pos < 0.1: score += 6
        elif bb_pos < 0.25: score += 3
    else:
        if bb_pos < 0.1: score += 2

    # 距低加分
    if from_low < 5 and trend != "DN ▼": score += 5
    elif from_low < 10 and trend == "UP ▲": score += 3

    # 超跌反弹
    if chg_20d < -15 and momentum_accel > -1: score += 5

    # 飞刀惩罚
    if falling_knife: score -= 10

    # 动量
    if chg_3d > 1: score += 4
    elif chg_3d < -3: score -= 5

    score = max(0, min(100, score))

    # ==== 明日预测 ====
    # ATR 区间
    pred_range = atr * 0.85
    # 动量
    raw_momentum = cur - closes[-2]
    # 趋势强度
    if len(closes) >= 10:
        c10 = closes[-10:]
        ups = sum(1 for i in range(1, 10) if c10[i] > c10[i-1])
        t_str = abs(ups - (9-ups)) / 9
    else:
        t_str = 0.5

    # MA 回归偏差
    if ma50 > 0:
        ma_gap = (ma50 - cur) / cur
        ma_bias = ma_gap * cur * 0.25 * (1 - t_str * 0.7)
    else:
        ma_bias = 0

    # RSI 修正
    if rsi <= 25: rsi_bias = +atr * 0.3
    elif rsi <= 35: rsi_bias = +atr * 0.1
    elif rsi >= 75: rsi_bias = -atr * 0.3
    elif rsi >= 65: rsi_bias = -atr * 0.1
    else: rsi_bias = 0

    pred_close = cur + raw_momentum * 0.3 + ma_bias + rsi_bias
    max_dev = atr * 3
    pred_close = max(cur - max_dev, min(cur + max_dev, pred_close))
    pred_low = pred_close - pred_range
    pred_high = pred_close + pred_range

    # 方向预测
    direction = "▲ UP" if pred_close > cur * 1.001 else ("▼ DN" if pred_close < cur * 0.999 else "→ 平")

    # ==== 操作建议 ====
    if score >= 80 and trend == "UP ▲":
        action = "🔥 强烈买入"
        action_color = "green"
    elif score >= 70:
        action = "✅ 建议买入"
        action_color = "green"
    elif score >= 55:
        action = "⏳ 观望等待"
        action_color = "yellow"
    elif score >= 35:
        action = "⚠️ 谨慎持有"
        action_color = "yellow"
    else:
        action = "❌ 建议卖出"
        action_color = "red"

    # 信号
    signals = []
    if rsi < 30: signals.append(f"RSI{rsi:.0f}超卖")
    if rsi > 70: signals.append(f"RSI{rsi:.0f}超买")
    if pe_pct is not None and pe_pct < 15: signals.append(f"PE{pe_pct:.0f}%极低")
    if pe_pct is not None and pe_pct > 85: signals.append(f"PE{pe_pct:.0f}%偏高")
    if pb_pct is not None and pb_pct < 15: signals.append(f"PB{pb_pct:.0f}%极低")
    if from_low < 5: signals.append(f"距低{from_low:.1f}%")
    if macd > 0 and macd_val > dea.iloc[-1]: signals.append("MACD金叉")
    if falling_knife: signals.append("⚠️飞刀")
    if momentum_accel > 0 and chg_3d < 0: signals.append("跌速放缓")
    if bb_pos < 0.15 and not falling_knife: signals.append("布林下轨")

    return {
        "code": code,
        "price": round(cur, 2),
        "score": round(score, 1),
        "trend": trend,
        "direction": direction,
        "action": action,
        "rsi": round(rsi, 1),
        "ma20": round(ma20, 2),
        "ma50": round(ma50, 2),
        "macd": round(macd, 4),
        "atr": round(atr, 2),
        "bb_pos": round(bb_pos, 4),
        "low_all": round(low_all, 2),
        "high_all": round(high_all, 2),
        "from_low": round(from_low, 1),
        "from_high": round(from_high, 1),
        "chg_5d": round(chg_5d, 1),
        "chg_20d": round(chg_20d, 1),
        "pe_pct": round(pe_pct, 1) if pe_pct is not None else None,
        "pb_pct": round(pb_pct, 1) if pb_pct is not None else None,
        "pred_low": round(pred_low, 2),
        "pred_high": round(pred_high, 2),
        "pred_close": round(pred_close, 2),
        "pred_range": round(pred_range, 2),
        "signals": "; ".join(signals) if signals else "无特殊信号",
        "falling_knife": falling_knife,
        "momentum_accel": round(momentum_accel, 2),
        "data_days": len(closes),
        "last_date": str(dates[-1].date()) if hasattr(dates[-1], 'date') else str(dates[-1])[:10],
    }


def _read_valuation(code: str, kind: str) -> float | None:
    val_path = os.path.join(CACHE_DIR, f"valuation_{code}.csv")
    if not os.path.exists(val_path):
        return None
    try:
        vdf = pd.read_csv(val_path, index_col=0)
        hist_col = f"{kind}_history"
        cur_col = f"current_{kind}"
        if hist_col in vdf.columns and cur_col in vdf.columns:
            raw = str(vdf[hist_col].iloc[0])
            if raw and raw != "nan":
                vals = [float(x) for x in raw.split("|") if x.strip()]
                if vals and len(vals) > 10:
                    cur_val = float(vdf[cur_col].iloc[0])
                    pct = np.sum(np.array(vals) < cur_val) / len(vals) * 100
                    return float(pct)
    except Exception:
        pass
    return None


def get_realtime_price(code: str) -> float | None:
    """从腾讯 API 获取实时价格。"""
    import urllib.request
    import json

    # 判断市场前缀
    if code.startswith("6"):
        full = f"sh{code}"
    elif code.startswith("0") or code.startswith("3"):
        full = f"sz{code}"
    elif code.startswith("9"):
        full = f"nq{code}"
    else:
        full = f"sh{code}"

    try:
        url = f"http://qt.gtimg.cn/q={full}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode("gbk", errors="replace")
        # 解析: v_sh600104="...数据..."
        for line in data.split("\n"):
            if "=" in line and "~" in line:
                parts = line.split("=", 1)[1].strip().strip('";').split("~")
                if len(parts) >= 4:
                    try:
                        return float(parts[3])  # parts[3] = 当前价
                    except ValueError:
                        pass
    except Exception:
        pass
    return None


def parse_portfolio() -> list[dict]:
    """解析 portfolio.txt 获取持仓列表。"""
    stocks = []
    if not os.path.exists(PORTFOLIO_FILE):
        print("❌ portfolio.txt 不存在")
        return stocks

    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(("-", "=", "持", "代", "总", " ")):
                continue
            parts = line.split()
            if len(parts) >= 3 and parts[0].isdigit() and len(parts[0]) == 6:
                try:
                    stocks.append({
                        "code": parts[0],
                        "name": parts[1],
                        "shares": int(parts[2]),
                        "avg_price": float(parts[3]),
                    })
                except (ValueError, IndexError):
                    continue
    return stocks


def main():
    print("=" * 100)
    print(f"  📊 持仓股票明日趋势分析 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 100)

    stocks = parse_portfolio()
    if not stocks:
        print("❌ 未找到持仓股票")
        return

    print(f"\n📋 共 {len(stocks)} 只持仓股票\n")

    # 批量获取实时行情
    all_codes = [s["code"] for s in stocks]
    print(f"获取 {len(all_codes)} 只实时行情...", end=" ", flush=True)
    rt_data = _fetch_realtime_batch(all_codes)
    print(f"获取 {len(rt_data)} 只")

    results = []
    for i, s in enumerate(stocks):
        code = s["code"]
        print(f"  [{i+1}/{len(stocks)}] 分析 {code} {s['name']}...", end=" ", flush=True)
        result = analyze_stock(code)
        if result:
            rt = rt_data.get(code, {})
            rt_price = rt.get("price")
            rt_name = rt.get("name")
            if rt_price and rt_price > 0:
                result["price"] = rt_price
                if result.get("low_all", 0) > 0:
                    result["from_low"] = round((rt_price - result["low_all"]) / result["low_all"] * 100, 1)
                if result.get("high_all", 0) > 0:
                    result["from_high"] = round((rt_price / result["high_all"] - 1) * 100, 1)
                result["realtime"] = True
            if rt_name:
                result["name"] = rt_name
            else:
                result["name"] = s["name"]
            result["shares"] = s["shares"]
            result["avg_price"] = s["avg_price"]
            if s["avg_price"] > 0:
                result["pnl_pct"] = round((result["price"] - s["avg_price"]) / s["avg_price"] * 100, 1)
                result["pnl_val"] = round((result["price"] - s["avg_price"]) * s["shares"], 0)
            else:
                result["pnl_pct"] = 0
                result["pnl_val"] = 0
            results.append(result)
            print(f"✅ 评分{result['score']} {result['trend']} {result['action']}")
        else:
            print("❌ 数据不足")

    if not results:
        print("\n❌ 所有股票数据不足，请先运行数据获取")
        return

    # ==== 汇总输出 ====
    print("\n")
    print("═" * 100)
    print("  📋 持仓分析总览")
    print("═" * 100)

    # 表头
    header = f"{'代码':<8} {'名称':<8} {'现价':>7} {'均价':>7} {'盈亏%':>7} {'评分':>5} {'趋势':<6} {'RSI':>5} {'距低%':>6} {'距高%':>7} {'方向':<6} {'操作建议':<14} {'信号'}"
    print(header)
    print("-" * 100)

    # 按评分排序
    results.sort(key=lambda x: x["score"], reverse=True)

    total_pnl = 0
    total_cost = 0
    up_count = 0
    strong_buy = 0

    for r in results:
        pnl_pct_str = f"{r['pnl_pct']:+.1f}%" if r.get('pnl_pct') else "N/A"
        total_pnl += r.get('pnl_val', 0)
        total_cost += r["shares"] * r["avg_price"]
        if "UP" in r["trend"]:
            up_count += 1
        if r["score"] >= 70:
            strong_buy += 1

        print(
            f"{r['code']:<8} {r['name']:<8} {r['price']:>7.2f} {r['avg_price']:>7.2f} "
            f"{pnl_pct_str:>7} {r['score']:>5.0f} {r['trend']:<6} {r['rsi']:>5.0f} "
            f"{r['from_low']:>6.1f} {r['from_high']:>7.1f} {r['direction']:<6} "
            f"{r['action']:<14} {r['signals'][:50]}"
        )

    print("-" * 100)
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    print(f"  总投入: {total_cost:,.0f}  总盈亏: {total_pnl:+,.0f} ({total_pnl_pct:+.1f}%)  UP: {up_count}/{len(results)}  强烈买入: {strong_buy}")

    # ==== 明日预测详情 ====
    print("\n")
    print("═" * 100)
    print("  🔮 明日价格预测（68%置信区间）")
    print("═" * 100)
    print(f"{'代码':<8} {'名称':<8} {'现价':>7} {'预测价':>7} {'预测低':>7} {'预测高':>7} {'区间宽':>7} {'方向':<6} {'评分':>5}")
    print("-" * 90)

    for r in results:
        print(
            f"{r['code']:<8} {r['name']:<8} {r['price']:>7.2f} {r['pred_close']:>7.2f} "
            f"{r['pred_low']:>7.2f} {r['pred_high']:>7.2f} "
            f"{r['pred_range']:>7.2f} {r['direction']:<6} {r['score']:>5.0f}"
        )

    # ==== 评分分布 ====
    print("\n")
    print("═" * 100)
    print("  📊 评分分布")
    print("═" * 100)

    ranges = [(80, 100, "🔥 强烈买入"), (70, 79, "✅ 建议买入"), (55, 69, "⏳ 观望等待"),
              (35, 54, "⚠️ 谨慎持有"), (0, 34, "❌ 建议卖出")]
    for lo, hi, label in ranges:
        stocks_in_range = [r for r in results if lo <= r["score"] <= hi]
        if stocks_in_range:
            names = ", ".join(f"{r['code']} {r['name']}({r['score']:.0f})" for r in stocks_in_range)
            print(f"  {label} ({lo}-{hi}): {len(stocks_in_range)}只 — {names}")

    # ==== 风险警示 ====
    print("\n")
    print("═" * 100)
    print("  ⚠️ 风险警示")
    print("═" * 100)

    warnings_list = []
    for r in results:
        if r["falling_knife"]:
            warnings_list.append(f"🔪 {r['code']} {r['name']}: 加速下跌飞刀！评分{r['score']:.0f} 趋势{r['trend']}")
        if r["from_low"] < 2 and "DN" in r["trend"]:
            warnings_list.append(f"📉 {r['code']} {r['name']}: 逼近历史最低{r['from_low']:.1f}%，趋势向下")
        if r.get("pnl_pct", 0) < -20:
            warnings_list.append(f"💀 {r['code']} {r['name']}: 亏损{r['pnl_pct']:.1f}%，深度套牢")

    if warnings_list:
        for w in warnings_list:
            print(f"  {w}")
    else:
        print("  ✅ 无高风险警示")

    # ==== 操作建议汇总 ====
    print("\n")
    print("═" * 100)
    print("  💡 明日操作建议")
    print("═" * 100)

    buy_candidates = [r for r in results if r["score"] >= 70 and "UP" in r["trend"]]
    hold_candidates = [r for r in results if 55 <= r["score"] < 70]
    sell_candidates = [r for r in results if r["score"] < 35]

    if buy_candidates:
        print(f"\n  🟢 可考虑加仓 ({len(buy_candidates)}只):")
        for r in buy_candidates:
            print(f"     {r['code']} {r['name']} | 评分{r['score']:.0f} | {r['signals']}")

    if hold_candidates:
        print(f"\n  🟡 继续持有观望 ({len(hold_candidates)}只):")
        for r in hold_candidates:
            print(f"     {r['code']} {r['name']} | 评分{r['score']:.0f} | 趋势{r['trend']}")

    if sell_candidates:
        print(f"\n  🔴 建议减仓/卖出 ({len(sell_candidates)}只):")
        for r in sell_candidates:
            print(f"     {r['code']} {r['name']} | 评分{r['score']:.0f} | {r['signals']}")

    print(f"\n  UP趋势占比: {up_count}/{len(results)} ({up_count/len(results)*100:.0f}%)")
    print(f"  平均评分: {np.mean([r['score'] for r in results]):.0f}")
    print(f"  总盈亏: {total_pnl:+,.0f}元 ({total_pnl_pct:+.1f}%)")
    if total_pnl_pct < -10:
        print(f"  ⚠️ 账户整体亏损超过10%，建议减少操作，等待反弹")

    print("\n" + "=" * 100)
    print("  ⚠️ 免责声明：以上分析基于历史数据和量化模型，仅供参考，不构成投资建议。")
    print("  股市有风险，投资需谨慎。请独立做出交易决策。")
    print("=" * 100)


if __name__ == "__main__":
    main()
