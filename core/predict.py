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
        base_atr_range = result.atr_14 * 0.8
    else:
        base_atr_range = cur_price * 0.02  # 回退: 当前价的2%

    # ── MA 均值回归（按偏离比例缩放）─────────────────────
    ma_bias = 0.0
    if result.ma_20 and result.ma_50 and cur_price > 0:
        gap_pct = (result.ma_50 - cur_price) / cur_price
        ma_bias = max(-0.5, min(0.5, gap_pct * cur_price * 0.3))

    # ── RSI 修正（4档）──────────────────────────────────
    rsi_bias = 0.0
    if result.rsi_14 is not None:
        if result.rsi_14 <= 25:
            rsi_bias = +0.5
        elif result.rsi_14 <= 35:
            rsi_bias = +0.2
        elif result.rsi_14 >= 75:
            rsi_bias = -0.5
        elif result.rsi_14 >= 65:
            rsi_bias = -0.2

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
