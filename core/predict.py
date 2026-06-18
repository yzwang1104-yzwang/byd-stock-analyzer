"""共享价格预测模块 — 消除 main.py 和 improvement_loop.py 的重复逻辑。

所有预测计算集中在此，两个入口统一调用。
"""

import statistics as _stats

from core.prediction_tracker import get_calibration, record_prediction
from core.market_context import market_range_multiplier


def compute_price_prediction(
    prices: list,
    result,  # AnalysisResult
    stock: str,
    cur_price: float,
    market: dict,
) -> dict:
    """计算价格预测区间。

    Args:
        prices: PriceBar 列表（最近>=4条）
        result: AnalysisResult
        stock: 股票代码
        cur_price: 当前实时价格
        market: 市场环境 dict

    Returns:
        dict with: pred_close, pred_low, pred_high, record_id, momentum,
                   ma_bias, rsi_bias, atr_range
    """
    closes = [p.close for p in prices[-20:]]
    stdev = _stats.stdev(closes) if len(closes) >= 2 else 0.0

    # ── 动量（3日加权）──────────────────────────────────
    momentum = 0.0
    if len(prices) >= 4:
        raw = (
            (prices[-1].close - prices[-2].close) * 0.5
            + (prices[-2].close - prices[-3].close) * 0.3
            + (prices[-3].close - prices[-4].close) * 0.2
        )
        max_move = (result.atr_14 or stdev) * 1.5
        momentum = max(-max_move, min(max_move, raw))

    # ── ATR 基础区间 ────────────────────────────────────
    if result.atr_14 is not None and result.atr_14 > 0:
        base_atr_range = result.atr_14 * 0.85  # 0.80→0.85 目标区间命中95%+
    else:
        base_atr_range = cur_price * 0.02  # 回退: 当前价的2%

    # ── 动量扩展：持续下跌/上涨时自动加宽区间 ────────────
    # 用5日动量判断方向强度，强趋势 = 更大的不确定性
    if len(prices) >= 6:
        mom_5d = (prices[-1].close - prices[-6].close) / prices[-6].close
        mom_strength = abs(mom_5d)
        if mom_strength > 0.05:   # 5日累计涨跌>5% → 强趋势
            base_atr_range *= 1.5
        elif mom_strength > 0.03:  # 3-5% → 中等趋势
            base_atr_range *= 1.3
        elif mom_strength > 0.02:  # 2-3% → 温和趋势
            base_atr_range *= 1.15

    # ── 趋势强度：强趋势时减弱均值回归倾向 ────────────────
    trend_strength = 0.0
    if len(prices) >= 10:
        # 10日价格路径的一致性：连续同向天数越多 → 趋势越强
        closes_10 = [p.close for p in prices[-10:]]
        ups = sum(1 for i in range(1, 10) if closes_10[i] > closes_10[i - 1])
        downs = 9 - ups
        # 0=完全震荡, 1=完全单边
        trend_strength = abs(ups - downs) / 9

    # ── MA 均值回归（按偏离比例缩放）─────────────────────
    ma_bias = 0.0
    if result.ma_20 and result.ma_50 and cur_price > 0:
        gap_pct = (result.ma_50 - cur_price) / cur_price
        raw_ma_bias = max(-0.5, min(0.5, gap_pct * cur_price * 0.3))
        # 强趋势时减弱均值回归（顺势而为）
        ma_bias = raw_ma_bias * (1 - trend_strength * 0.7)

    # ── RSI 修正（4档），强趋势时减弱 ────────────────────
    rsi_bias = 0.0
    if result.rsi_14 is not None:
        if result.rsi_14 <= 25:
            raw_rsi_bias = +0.5
        elif result.rsi_14 <= 35:
            raw_rsi_bias = +0.2
        elif result.rsi_14 >= 75:
            raw_rsi_bias = -0.5
        elif result.rsi_14 >= 65:
            raw_rsi_bias = -0.2
        else:
            raw_rsi_bias = 0.0
        rsi_bias = raw_rsi_bias * (1 - trend_strength * 0.7)

    # ── 校准偏差 ────────────────────────────────────────
    cal = get_calibration(stock)
    cal_bias = cal.get("bias_correction", 0.0)
    cal_range_mult = cal.get("range_multiplier", 1.0)
    mkt_mult = market_range_multiplier(market)

    # ── 综合预测 ────────────────────────────────────────
    pred_close = cur_price + momentum * 0.3 + ma_bias + rsi_bias + cal_bias
    pred_range = base_atr_range * cal_range_mult * mkt_mult

    # 安全钳制：不超过 ATR×3
    max_dev = (result.atr_14 or stdev) * 3
    pred_close = max(cur_price - max_dev, min(cur_price + max_dev, pred_close))
    pred_low = pred_close - pred_range
    pred_high = pred_close + pred_range

    # ── 记录 ────────────────────────────────────────────
    rid = record_prediction(
        stock_code=stock,
        predicted_low=pred_low,
        predicted_high=pred_high,
        predicted_close=pred_close,
        current_price=cur_price,
    )

    return {
        "pred_close": round(pred_close, 2),
        "pred_low": round(pred_low, 2),
        "pred_high": round(pred_high, 2),
        "record_id": rid,
        "momentum": round(momentum, 3),
        "ma_bias": round(ma_bias, 3),
        "rsi_bias": round(rsi_bias, 3),
        "atr_range": round(pred_range, 2),
    }
