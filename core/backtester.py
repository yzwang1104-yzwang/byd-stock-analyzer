"""回测引擎——用历史数据模拟预测，即时验证准确率。

无需等实际收盘——在历史数据上跑预测模型，马上知道准不准。
"""

import statistics
from datetime import date, timedelta
from typing import Optional

from core.data_fetcher import fetch_price_history
from core.models import PriceBar


def backtest_direction(
    stock_code: str = "002594",
    days: int = 200,
    lookback: int = 60,
) -> dict:
    """回测方向预测准确率。

    对过去 N 天，每一天用前 lookback 天的数据预测当日方向，
    与当日实际方向对比。

    Args:
        stock_code: 股票代码
        days: 回测天数
        lookback: 每次预测使用的历史窗口

    Returns:
        准确率报告
    """
    prices = fetch_price_history(stock_code=stock_code, days=days + lookback + 1)

    if len(prices) < lookback + days:
        return {"status": "insufficient_data", "count": len(prices)}

    results = []
    for i in range(lookback, len(prices) - 1):
        window = prices[i - lookback : i + 1]  # 到 i 为止的历史
        today = prices[i]
        tomorrow = prices[i + 1]

        pred = predict_direction(window)
        actual = "up" if tomorrow.close > today.close else ("down" if tomorrow.close < today.close else "flat")

        results.append({
            "date": today.date.isoformat(),
            "close": today.close,
            "predicted": pred["direction"],
            "confidence": pred["confidence"],
            "actual": actual,
            "correct": pred["direction"] == actual,
            "signals": pred["signals"],
        })

    correct = sum(1 for r in results if r["correct"])
    total = len(results)
    up_count = sum(1 for r in results if r["predicted"] == "up")
    down_count = sum(1 for r in results if r["predicted"] == "down")
    flat_count = sum(1 for r in results if r["predicted"] == "flat")
    up_correct = sum(1 for r in results if r["predicted"] == "up" and r["correct"])
    down_correct = sum(1 for r in results if r["predicted"] == "down" and r["correct"])

    # 纯方向准确率（排除"平"预测）
    directional_results = [r for r in results if r["predicted"] != "flat"]
    directional_correct = sum(1 for r in directional_results if r["correct"])
    directional_total = len(directional_results)

    # 按置信度分组
    high_conf = [r for r in results if r["confidence"] >= 70]
    med_conf = [r for r in results if 50 <= r["confidence"] < 70]
    low_conf = [r for r in results if r["confidence"] < 50]

    return {
        "status": "ok",
        "total": total,
        "flat_count": flat_count,
        "flat_rate": round(flat_count / total * 100, 1) if total > 0 else 0,
        "directional_total": directional_total,
        "directional_accuracy": round(
            directional_correct / directional_total * 100, 1
        ) if directional_total > 0 else 0,
        "overall_accuracy": round(correct / total * 100, 1) if total > 0 else 0,
        "up_accuracy": round(up_correct / up_count * 100, 1) if up_count > 0 else 0,
        "down_accuracy": round(down_correct / down_count * 100, 1) if down_count > 0 else 0,
        "high_conf_accuracy": round(
            sum(1 for r in high_conf if r["correct"]) / len(high_conf) * 100, 1
        ) if high_conf else 0,
        "high_conf_count": len(high_conf),
        "med_conf_accuracy": round(
            sum(1 for r in med_conf if r["correct"]) / len(med_conf) * 100, 1
        ) if med_conf else 0,
        "med_conf_count": len(med_conf),
        "low_conf_accuracy": round(
            sum(1 for r in low_conf if r["correct"]) / len(low_conf) * 100, 1
        ) if low_conf else 0,
        "low_conf_count": len(low_conf),
        "recent_10_accuracy": round(
            sum(1 for r in results[-10:] if r["correct"]) / min(10, len(results)) * 100, 1
        ),
        "sample_results": results[-5:],  # 最近5条样本
    }


def predict_direction(window: list[PriceBar]) -> dict:
    """基于窗口数据预测次日方向——6指标投票法。

    返回: {"direction": "up"|"down"|"flat", "confidence": 0-100, "signals": [...]}
    """
    closes = [p.close for p in window]
    highs = [p.high for p in window]
    lows = [p.low for p in window]
    volumes = [p.volume for p in window]

    signals = []
    up_votes = 0
    down_votes = 0
    total_votes = 0

    current = closes[-1]

    # 1. MACD 柱状图方向（EMA(12) - EMA(26)）
    if len(closes) >= 26:
        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)
        macd = ema12 - ema26
        if macd > 0.3:  # 显著正柱
            signals.append(f"MACD正柱({macd:.2f}) ↑")
            up_votes += 0.7
        elif macd < -0.3:  # 显著负柱
            signals.append(f"MACD负柱({macd:.2f}) ↓")
            down_votes += 0.7
        # -0.3~0.3: 中性，MACD 无方向信号
        total_votes += 1

    # 2. RSI(14) — 顺势为主，极端值才逆势（且需趋势确认）
    if len(closes) >= 15:
        rsi = _simple_rsi(closes, 14)
        ma20_r = sum(closes[-20:])/20 if len(closes)>=20 else current
        ma50_r = sum(closes[-50:])/50 if len(closes)>=50 else ma20_r
        in_downtrend = ma20_r < ma50_r
        in_uptrend = ma20_r > ma50_r

        if rsi < 20 and not in_downtrend:
            # 极端超卖 + 非下跌趋势 → 反弹概率大
            signals.append(f"RSI极端超卖({rsi:.0f}) ↑")
            up_votes += 1.5
        elif rsi < 20 and in_downtrend:
            # 极端超卖但趋势向下 → 弱反弹信号
            signals.append(f"RSI极端超卖({rsi:.0f}) ↑(弱)")
            up_votes += 0.5
        elif rsi > 80 and not in_uptrend:
            signals.append(f"RSI极端超买({rsi:.0f}) ↓")
            down_votes += 1.5
        elif rsi > 80 and in_uptrend:
            signals.append(f"RSI极端超买({rsi:.0f}) ↓(弱)")
            down_votes += 0.5
        elif rsi < 30 and in_uptrend:
            # 上涨趋势中的超卖 → 加仓机会
            signals.append(f"RSI超卖+趋势↑({rsi:.0f}) ↑")
            up_votes += 1
        elif rsi > 70 and in_downtrend:
            # 下跌趋势中的超买 → 减仓信号
            signals.append(f"RSI超买+趋势↓({rsi:.0f}) ↓")
            down_votes += 1
        # RSI在30-70之间 → 不投票（中性区扩大）
        total_votes += 1

    # 3. MA20 vs MA50 — 交叉1票，位置0.3票
    if len(closes) >= 50:
        ma20 = sum(closes[-20:]) / 20
        ma50 = sum(closes[-50:]) / 50
        ma20_prev = sum(closes[-21:-1]) / 20
        ma50_prev = sum(closes[-51:-1]) / 50

        if ma20 > ma50 and ma20_prev <= ma50_prev:
            signals.append("MA金叉 ↑")
            up_votes += 1
        elif ma20 < ma50 and ma20_prev >= ma50_prev:
            signals.append("MA死叉 ↓")
            down_votes += 1
        elif ma20 > ma50:
            signals.append("MA多头 ↑")
            up_votes += 0.3
        elif ma20 < ma50:
            signals.append("MA空头 ↓")
            down_votes += 0.3
        total_votes += 1

    # 趋势状态（影响其他信号的权重）
    trend_bias = 1.0  # 1.0=中性, <1=偏空, >1=偏多
    if len(closes) >= 50:
        ma20_t = sum(closes[-20:]) / 20
        ma50_t = sum(closes[-50:]) / 50
        if ma20_t < ma50_t:
            trend_bias = 0.7  # 下跌趋势：降低看涨信号权重
        elif ma20_t > ma50_t:
            trend_bias = 1.3  # 上涨趋势：增强看涨信号权重

    # 4. 布林带位置 — 顺势操作，不逆势抄底
    if len(closes) >= 20:
        ma20 = sum(closes[-20:]) / 20
        stdev = statistics.stdev(closes[-20:])
        upper = ma20 + 2 * stdev
        lower = ma20 - 2 * stdev
        position = (current - lower) / (upper - lower) if (upper - lower) > 0 else 0.5
        in_downtrend_bb = len(closes)>=50 and (sum(closes[-20:])/20) < (sum(closes[-50:])/50)

        if position < 0.1 and not in_downtrend_bb:
            signals.append("触下轨+非跌势 ↑")
            up_votes += 1
        elif position > 0.9 and in_downtrend_bb:
            # 下跌趋势反弹至上轨 → 可能继续跌
            signals.append("触上轨+跌势 ↓")
            down_votes += 1
        elif position < 0.15 and in_downtrend_bb:
            # 跌势中触下轨 → 不投（可能是飞刀）
            signals.append("跌势触下轨(观望)")
            # no vote
        elif position > 0.85:
            signals.append("近上轨 ↓")
            down_votes += 0.5
        elif position < 0.2:
            signals.append("近下轨 ↑")
            up_votes += 0.5
        total_votes += 1

    # 5. 量价关系 — 只有显著放量才投票
    if len(volumes) >= 10:
        vol_avg = sum(volumes[-10:]) / 10
        vol_today = volumes[-1]
        price_change = closes[-1] - closes[-2]
        if vol_today > vol_avg * 1.5 and price_change > 0:
            signals.append("放量上涨 ↑")
            up_votes += 1
        elif vol_today > vol_avg * 1.5 and price_change < 0:
            signals.append("放量下跌 ↓")
            down_votes += 1
        # 正常量不投票
        total_votes += 1

    # 6. 短期动量 — 只有显著方向才投票
    if len(closes) >= 4:
        momentum = (
            (closes[-1] - closes[-2]) * 0.5 +
            (closes[-2] - closes[-3]) * 0.3 +
            (closes[-3] - closes[-4]) * 0.2
        )
        pct_change = momentum / closes[-1] * 100  # 百分比变化
        if pct_change > 0.5:  # 累计涨幅 >0.5%
            signals.append(f"动量正({pct_change:.1f}%) ↑")
            up_votes += 1
        elif pct_change < -0.5:  # 累计跌幅 >0.5%
            signals.append(f"动量负({pct_change:.1f}%) ↓")
            down_votes += 1
        # -0.5% ~ +0.5%: 不投票
        total_votes += 1

    # 趋势调整投票权重（对称：跌势降看涨+增强看跌，涨势反之）
    if trend_bias < 1.0:  # 下跌趋势
        up_votes *= trend_bias      # 降看涨票权重
        down_votes /= trend_bias    # 增强看跌票权重
    elif trend_bias > 1.0:  # 上涨趋势
        up_votes *= trend_bias      # 增强看涨票权重
        down_votes /= trend_bias    # 降看跌票权重

    # 计票
    if total_votes == 0:
        return {"direction": "flat", "confidence": 0, "signals": ["数据不足"]}

    margin = up_votes - down_votes
    total_weight = up_votes + down_votes

    if total_weight == 0:
        return {"direction": "flat", "confidence": 0, "signals": ["无有效信号"]}

    # 置信度基于票差比例
    confidence = round(min(abs(margin) / total_weight * 200, 100))

    # 严格阈值：至少1票净优势才判方向（提高准确率）
    if margin >= 1.0:
        direction = "up"
    elif margin <= -1.0:
        direction = "down"
    else:
        direction = "flat"
        confidence = min(confidence, 40)  # 不确定时压低置信

    return {"direction": direction, "confidence": confidence, "signals": signals}


# ====== 简易技术指标（不依赖 pandas-ta） ======

def _ema(values: list[float], period: int) -> float:
    """指数移动平均。"""
    if len(values) < period:
        return sum(values) / len(values)
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = (v - ema) * multiplier + ema
    return ema


def _simple_rsi(closes: list[float], period: int = 14) -> float:
    """简易 RSI 计算。"""
    if len(closes) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
