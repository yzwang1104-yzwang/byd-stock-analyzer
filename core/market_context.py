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


def get_market_regime() -> dict:
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

    # 趋势: MA20 vs MA50
    ma20 = sum(closes[-20:]) / 20
    ma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else ma20
    trend_score = 50
    if ma20 > ma50 * 1.02:
        regime = "bull"
        trend_score = 75
    elif ma20 < ma50 * 0.98:
        regime = "bear"
        trend_score = 25
    else:
        regime = "sideways"

    # RSI(14)
    rsi = _simple_rsi(closes, 14)

    # 近期动量
    momentum_5d = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0

    # 近10日涨跌比
    ups = sum(1 for i in range(-10, 0) if closes[i] > closes[i - 1])
    up_ratio = ups / 10 * 100

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
    gains, losses = [], []
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains.append(diff); losses.append(0)
        else:
            gains.append(0); losses.append(abs(diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
