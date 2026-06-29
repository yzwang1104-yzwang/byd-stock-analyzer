"""共享快速分析器——所有扫描工具的标准分析函数。

设计目标：
    一个函数，一份标准输出 schema，所有 CLI/Web 工具共用一个入口。
    从此任何新建工具自动获得 历史最低/最高 等所有标准字段。

标准字段清单（28 个）：
    基础: code, price, score, rsi, trend, chg_20d, chg_3d, chg_5d
    技术: ma20, ma50, macd, macd_signal, bb_pos
    估值: pe_pct, pb_pct
    历史: low_all, from_low, high_all, from_high
    动量: momentum_accel, falling_knife
    信号: signals (列表)
    其他: data_days, atr_pct

usage:
    from core.quick_analyzer import analyze_stock

    result = analyze_stock("002594")
    if result:
        print(f"评分: {result['score']}, 距低: {result['from_low']:.0f}%, 距高: {result['from_high']:.0f}%")
"""

import os
import numpy as np
import pandas as pd
from typing import Optional


def analyze_stock(code: str, cache_dir: str = ".cache") -> Optional[dict]:
    """快速分析单只股票，返回 28 个标准字段。

    Args:
        code: 股票代码，如 "002594"
        cache_dir: 缓存目录路径

    Returns:
        dict 或 None（数据不足或缓存缺失时）
    """
    price_path = os.path.join(cache_dir, f"prices_{code}.csv")
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

    # ====== 历史最低/最高（永久字段） ======
    low_all = float(np.min(closes))
    high_all = float(np.max(closes))
    from_low = (cur - low_all) / low_all * 100
    from_high = (cur / high_all - 1) * 100

    # ====== 均线 ======
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else ma20

    # ====== RSI(14) ======
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    rsi = float(rsi_series.iloc[-1]) if not np.isnan(rsi_series.iloc[-1]) else 50.0

    # ====== MACD ======
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd = float(dif.iloc[-1] - dea.iloc[-1])
    macd_signal = float(dea.iloc[-1])

    # ====== 布林带位置 ======
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_low = bb_mid - 2 * bb_std
    bb_pos = float((close.iloc[-1] - bb_low.iloc[-1]) / (4 * bb_std.iloc[-1])) if bb_std.iloc[-1] > 0 else 0.5

    # ====== ATR% ======
    trs = []
    for i in range(-20, 0):
        h = float(df.iloc[i]["high"]) if "high" in df.columns else closes[i]
        l = float(df.iloc[i]["low"]) if "low" in df.columns else closes[i]
        prev_c = closes[i - 1]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    atr_pct = float(np.mean(trs) / cur * 100) if cur > 0 else 0.0

    # ====== 涨跌幅 ======
    chg_20d = (cur - float(closes[-21])) / float(closes[-21]) * 100 if len(closes) >= 21 else 0
    chg_5d = (cur - float(closes[-6])) / float(closes[-6]) * 100 if len(closes) >= 6 else 0
    chg_3d = (cur - float(closes[-4])) / float(closes[-4]) * 100 if len(closes) >= 4 else 0

    # ====== 趋势 ======
    if ma20 > ma50 * 1.01:
        trend = "up"
    elif ma20 < ma50 * 0.99:
        trend = "down"
    else:
        trend = "sideways"

    # ====== 动量 ======
    momentum_accel = chg_3d - chg_5d
    falling_knife = trend == "down" and chg_3d < -3 and momentum_accel < -1

    # ====== 估值 ======
    pe_pct = _read_valuation_percentile(code, cache_dir, "pe")
    pb_pct = _read_valuation_percentile(code, cache_dir, "pb")

    # ====== 评分 ======
    score = 50.0

    # PE 分位
    if pe_pct is not None:
        score += max(0, min(20, (1 - pe_pct / 100) * 20))
    if pb_pct is not None:
        score += max(0, min(10, (1 - pb_pct / 100) * 10))

    # RSI
    if not np.isnan(rsi):
        if trend == "up":
            if rsi < 25: score += 12
            elif rsi < 30: score += 8
            elif rsi < 35: score += 5
        elif trend == "sideways":
            if rsi < 25: score += 8
            elif rsi < 30: score += 5
        else:
            if rsi < 25 and momentum_accel > -0.5: score += 5
            elif rsi < 30 and momentum_accel > 0: score += 3

    # 趋势
    if trend == "up": score += 10
    elif trend == "sideways": score += 4
    else: score -= 5

    # MACD
    if macd > 0: score += 5

    # BB
    if not np.isnan(bb_pos):
        if not falling_knife:
            if bb_pos < 0.1: score += 6
            elif bb_pos < 0.25: score += 3
        else:
            if bb_pos < 0.1: score += 2

    # 超跌反弹
    if chg_20d < -15 and momentum_accel > -1:
        score += 5

    # 飞刀惩罚
    if falling_knife:
        score -= 8

    # 短期动量
    if chg_3d > 1: score += 4
    elif chg_3d < -3: score -= 4

    score = max(0, min(100, score))

    # ====== 信号 ======
    signals = []
    if not np.isnan(rsi) and rsi < 30:
        signals.append(f"RSI{rsi:.0f}超卖")
    if pe_pct is not None and pe_pct < 15: signals.append(f"PE{pe_pct:.0f}%极低")
    if pb_pct is not None and pb_pct < 15: signals.append(f"PB{pb_pct:.0f}%极低")
    if macd > 0: signals.append("MACD金叉")
    if trend == "up": signals.append("趋势向上")
    if chg_20d < -15: signals.append(f"超跌{chg_20d:.0f}%")
    if falling_knife: signals.append("⚠️加速下跌")
    if momentum_accel > 0 and chg_3d < 0: signals.append("跌速放缓")
    if not np.isnan(bb_pos) and bb_pos < 0.15 and not falling_knife:
        signals.append("布林下轨超卖")

    return {
        # 基础
        "code": code, "price": round(cur, 2), "score": round(score, 1),
        "rsi": round(rsi, 1) if not np.isnan(rsi) else None,
        "trend": trend, "chg_20d": round(chg_20d, 1),
        "chg_3d": round(chg_3d, 1), "chg_5d": round(chg_5d, 1),
        # 技术
        "ma20": round(ma20, 2), "ma50": round(ma50, 2),
        "macd": round(macd, 4), "macd_signal": round(macd_signal, 4),
        "bb_pos": round(bb_pos, 4) if not np.isnan(bb_pos) else None,
        "atr_pct": round(atr_pct, 2),
        # 估值
        "pe_pct": round(pe_pct, 1) if pe_pct is not None else None,
        "pb_pct": round(pb_pct, 1) if pb_pct is not None else None,
        # 历史（永久字段）
        "low_all": round(low_all, 2),
        "from_low": round(from_low, 1),
        "high_all": round(high_all, 2),
        "from_high": round(from_high, 1),
        # 动量
        "momentum_accel": round(momentum_accel, 2),
        "falling_knife": falling_knife,
        # 信号
        "signals": "; ".join(signals) if signals else "无特殊信号",
        "signals_list": signals,
        # 其他
        "data_days": len(closes),
    }


def _read_valuation_percentile(code: str, cache_dir: str, kind: str) -> Optional[float]:
    """从缓存读取 PE/PB 分位值。"""
    val_path = os.path.join(cache_dir, f"valuation_{code}.csv")
    if not os.path.exists(val_path):
        return None
    try:
        vdf = pd.read_csv(val_path, index_col=0)
        hist_col = f"{kind}_history"
        cur_col = f"current_{kind}"
        if hist_col in vdf.columns and cur_col in vdf.columns:
            raw = str(vdf[hist_col].iloc[0]) if vdf[hist_col].iloc[0] else ""
            if raw:
                vals = [float(x) for x in raw.split("|") if x.strip()]
                if vals and len(vals) > 10:
                    cur_val = float(vdf[cur_col].iloc[0])
                    pct = np.sum(np.array(vals) < cur_val) / len(vals) * 100
                    return float(pct)
    except Exception:
        pass
    return None
