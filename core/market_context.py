"""市场环境——大盘指数 + 行业对比，为个股分析提供背景。

新增维度:
1. 上证指数(000001): 判断市场整体方向
2. 行业对比: 个股 vs 行业指数的相对强弱
"""

import statistics
from datetime import date
from typing import Optional

from core.data_fetcher import fetch_price_history
from core.models import PriceBar


def get_market_regime() -> dict[str, object]:
    """获取当前市场环境。

    Returns:
        regime: "bull" | "bear" | "sideways"
        market_trend: 大盘趋势得分 0-100
        market_rsi: 上证 RSI
        beta: 个股相对大盘的弹性（待实现）
    """
    try:
        # 上证50 ETF (510050) 作为大盘代理——与上证指数高度相关, 数据易获取
        sh_index = fetch_price_history("510050", days=60, force_refresh=False)
    except Exception:
        return {"regime": "unknown", "market_trend": 50, "note": "大盘数据获取失败"}

    if len(sh_index) < 30:
        return {"regime": "unknown", "market_trend": 50, "note": "数据不足"}

    closes = [p.close for p in sh_index]

    # 均线方向
    ma20 = sum(closes[-20:]) / 20
    ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else ma20

    # 今日涨跌
    today_change = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0

    # 近期动量
    momentum_5d = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
    momentum_10d = (closes[-1] - closes[-11]) / closes[-11] * 100 if len(closes) >= 11 else 0

    # RSI(14)
    rsi = _simple_rsi(closes, 14)

    # 近10日涨跌比
    ups = sum(1 for i in range(-10, 0) if closes[i] > closes[i - 1])
    up_ratio = ups / 10 * 100

    # === 多因子判定市场状态 ===
    bear_score = 0  # 越高越熊
    bull_score = 0  # 越高越牛

    # 因子1: 均线结构 (MA20 vs MA50) — 权重最高
    if ma20 > ma50 * 1.01:
        bull_score += 3
    elif ma20 < ma50 * 0.99:
        bear_score += 3

    # 因子2: 今日涨跌 — 用户最直观感受，且当日趋势最有预测力
    if today_change > 0.8:
        bull_score += 4
    elif today_change > 0.3:
        bull_score += 2
    elif today_change < -0.8:
        bear_score += 4
    elif today_change < -0.3:
        bear_score += 2

    # 因子3: 短期动量 (5日) — 阈值提高避免与今日冲突时压倒今日
    if momentum_5d > 3:
        bull_score += 2
    elif momentum_5d < -3:
        bear_score += 2

    # 因子4: 中期动量 (10日)
    if momentum_10d > 4:
        bull_score += 1
    elif momentum_10d < -4:
        bear_score += 1

    # 因子5: RSI
    if rsi > 60:
        bull_score += 1
    elif rsi < 40:
        bear_score += 1

    # 因子6: 涨跌比
    if up_ratio > 65:
        bull_score += 1
    elif up_ratio < 35:
        bear_score += 1

    # 判定（2分差距即可判定方向，更敏感）
    if bull_score >= bear_score + 2:
        regime = "bull"
        trend_score = min(100, 50 + (bull_score - bear_score) * 8)
    elif bear_score >= bull_score + 2:
        regime = "bear"
        trend_score = max(0, 50 - (bear_score - bull_score) * 8)
    else:
        regime = "sideways"
        trend_score = 50

    return {
        "regime": regime,
        "market_trend": trend_score,
        "market_rsi": round(rsi, 1),
        "momentum_5d_pct": round(momentum_5d, 2),
        "up_ratio_10d": round(up_ratio, 1),
        "index_level": round(closes[-1], 2),
        "ma20": round(ma20, 2),
        "ma50": round(ma50, 2),
        "note": "OK",
    }


def market_boost(score: float, market: dict) -> float:
    """根据市场环境调节评分。

    牛市: 个股评分上调（顺势而为）
    熊市: 个股评分下调（逆水行舟）
    震荡: 不变
    """
    if market.get("regime") == "bull":
        return min(100, score + 5)
    elif market.get("regime") == "bear":
        return max(0, score - 8)
    return score


def market_range_multiplier(market: dict) -> float:
    """根据市场波动率调整预测区间。

    熊市波动大 → 区间放宽
    牛市波动小 → 区间收窄
    """
    regime = market.get("regime", "unknown")
    if regime == "bear":
        return 1.3  # 熊市波动大，放宽30%
    elif regime == "bull":
        return 0.9  # 牛市趋势明确，收窄10%
    return 1.0


def _simple_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
