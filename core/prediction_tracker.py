"""预测追踪系统——记录每次预测，与实际结果比对，持续校准模型。

工作原理:
1. 每次运行记录: 时间、预测区间、实际价格
2. 积累足够数据后计算: 准确率、偏差方向、校准系数
3. 将校准结果反馈到评分模型
"""

import csv
import json
import statistics
from datetime import date, datetime
from pathlib import Path
from typing import Optional

TRACKER_DIR = Path(".prediction_history")
TRACKER_DIR.mkdir(parents=True, exist_ok=True)

# ====== 记录预测 ======

def record_prediction(
    stock_code: str,
    predicted_low: float,
    predicted_high: float,
    predicted_close: float,
    current_price: float,
    confidence: str = "中",
) -> int:
    """记录一次预测。返回记录 ID。"""
    records = _load_records(stock_code)
    record_id = len(records) + 1

    records.append({
        "id": record_id,
        "timestamp": datetime.now().isoformat(),
        "date": date.today().isoformat(),
        "predicted_low": round(predicted_low, 2),
        "predicted_high": round(predicted_high, 2),
        "predicted_close": round(predicted_close, 2),
        "current_price": round(current_price, 2),
        "confidence": confidence,
        "actual_close": "",  # 后续回填
        "error": "",         # 后续回填
    })

    _save_records(stock_code, records)
    return record_id


def backfill_actual(stock_code: str, actual_price: float) -> int:
    """回填实际收盘价，更新最新一条未回填的记录。"""
    records = _load_records(stock_code)
    count = 0
    for r in records:
        if not r["actual_close"]:
            r["actual_close"] = round(actual_price, 2)
            r["error"] = round(actual_price - float(r["predicted_close"]), 2)
            count += 1
    if count:
        _save_records(stock_code, records)
    return count


# ====== 校准分析 ======

def compute_accuracy(stock_code: str) -> dict:
    """计算预测准确率和偏差统计。"""
    records = _load_records(stock_code)
    completed = [r for r in records if r["actual_close"]]

    if len(completed) < 3:
        return {"status": "insufficient_data", "count": len(completed)}

    errors = [float(r["error"]) for r in completed]
    abs_errors = [abs(e) for e in errors]

    # 方向准确率（预测涨跌方向是否正确）
    direction_correct = 0
    for r in completed:
        pred_change = float(r["predicted_close"]) - float(r["current_price"])
        actual_change = float(r["actual_close"]) - float(r["current_price"])
        if (
            (pred_change > 0 and actual_change > 0) or
            (pred_change < 0 and actual_change < 0) or
            (abs(pred_change) < 0.1 and abs(actual_change) < 0.1 and pred_change * actual_change >= 0)
        ):
            direction_correct += 1

    # 是否在实际区间内
    in_range = sum(
        1 for r in completed
        if float(r["predicted_low"]) <= float(r["actual_close"]) <= float(r["predicted_high"])
    )

    return {
        "status": "ok",
        "count": len(completed),
        "total_predictions": len(records),
        "mae": round(statistics.mean(abs_errors), 2),          # 平均绝对误差
        "rmse": round(statistics.mean([e**2 for e in errors])**0.5, 2),
        "mean_bias": round(statistics.mean(errors), 2),        # 正=预测偏低, 负=预测偏高
        "direction_accuracy": round(direction_correct / len(completed) * 100, 1),
        "in_range_pct": round(in_range / len(completed) * 100, 1),
    }


def get_calibration(stock_code: str) -> dict:
    """获取校准参数——用于修正后续预测。"""
    stats = compute_accuracy(stock_code)
    if stats["status"] != "ok":
        return {"bias_correction": 0.0, "range_multiplier": 1.0, "ready": False}

    # 中位数偏差 + 指数加权（排除异常值）
    records = _load_records(stock_code)
    filled = [r for r in records if r["actual_close"] and abs(float(r["error"])) < 5.0]
    if len(filled) >= 3:
        import statistics as _st
        # 中位数偏差——比均值更稳健（不受极端值影响）
        median_bias = _st.median([float(r["error"]) for r in filled])
        # 指数加权偏差（最近10条）
        recent = filled[-10:]
        weighted = [float(r["error"]) * (1.5 ** i) for i, r in enumerate(recent)]
        ewma_bias = sum(weighted) / sum(1.5 ** i for i in range(len(weighted)))
        # 中位数和EWMA取平均
        bias = (median_bias + ewma_bias) / 2
    else:
        bias = stats["mean_bias"]

    # 样本量越大，修正力度越强
    n = len(filled)
    if n >= 30:
        correction_strength = 0.90  # 30+样本：90%修正
    elif n >= 15:
        correction_strength = 0.75
    elif n >= 5:
        correction_strength = 0.60
    else:
        correction_strength = 0.50

    # 连续命中：连续N次误差<阈值
    threshold = 0.3 if n < 10 else 0.2  # 样本多了收紧阈值
    consecutive = 0
    for r in reversed(filled):
        if abs(float(r["error"])) < threshold:
            consecutive += 1
        else:
            break

    # 区间收窄
    in_range = stats["in_range_pct"]
    range_mult = 1.0
    if in_range < 40:
        range_mult = 1.5
    elif in_range < 60:
        range_mult = 1.2
    elif in_range >= 98:
        range_mult = 0.35  # 几乎完美 → 激进收窄
    elif in_range >= 95:
        range_mult = 0.50
    elif in_range >= 90:
        range_mult = 0.65
    elif in_range >= 85:
        range_mult = 0.75
    elif in_range > 70:
        range_mult = 0.85

    # 连续命中奖励（更激进）
    if consecutive >= 15:
        range_mult *= 0.55
    elif consecutive >= 10:
        range_mult *= 0.70
    elif consecutive >= 5:
        range_mult *= 0.80
    elif consecutive >= 3:
        range_mult *= 0.90

    return {
        "bias_correction": round(bias * correction_strength, 2),
        "range_multiplier": round(range_mult, 2),
        "ready": True,
        "based_on": n,
        "direction_accuracy": stats["direction_accuracy"],
        "in_range_pct": in_range,
        "consecutive_hits": consecutive,
    }


# ====== 内部 ======

def _records_path(stock_code: str) -> Path:
    return TRACKER_DIR / f"predictions_{stock_code}.json"


def _load_records(stock_code: str) -> list[dict]:
    path = _records_path(stock_code)
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_records(stock_code: str, records: list[dict]) -> None:
    with open(_records_path(stock_code), "w") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
