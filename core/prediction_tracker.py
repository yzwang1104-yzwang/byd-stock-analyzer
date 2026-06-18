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


def _ensure_tracker_dir() -> None:
    """延迟创建追踪目录，避免模块导入时副作用。"""
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
        "actual_close": "",       # 后续回填
        "error": "",              # 后续回填
        "backfill_type": "",      # "auto"=30分钟自动, "manual"=手动回填
    })

    _save_records(stock_code, records)
    return record_id


def backfill_actual(stock_code: str, actual_price: float, fill_type: str = "manual") -> int:
    """回填实际收盘价，更新未回填记录。fill_type: 'auto'或'manual'。"""
    records = _load_records(stock_code)
    count = 0
    for r in records:
        if not r.get("actual_close"):
            r["actual_close"] = round(actual_price, 2)
            r["error"] = round(actual_price - float(r.get("predicted_close", 0)), 2)
            r["backfill_type"] = fill_type
            count += 1
    if count:
        _save_records(stock_code, records)
    return count


# ====== 校准分析 ======

def compute_accuracy(stock_code: str) -> dict:
    """计算预测准确率和偏差统计。自动过滤极端异常值。"""
    records = _load_records(stock_code)
    completed = [r for r in records if r.get("actual_close")]

    if len(completed) < 3:
        return {"status": "insufficient_data", "count": len(completed)}

    # 过滤极端异常值（偏差 > max(5元, 5%当前价)）
    ref_price = float(completed[-1].get("current_price", 100))
    threshold = max(5.0, ref_price * 0.05)
    valid = [r for r in completed if abs(float(r["error"])) < threshold]
    filtered_count = len(completed) - len(valid)

    errors = [float(r.get("error", 0) or 0) for r in valid]
    abs_errors = [abs(e) for e in errors if e != 0]

    # 方向准确率——只统计明确标记为 manual 的记录
    dir_records = [r for r in valid if r.get("backfill_type") == "manual"
                   and r.get("predicted_close") and r.get("current_price")]
    direction_correct = 0
    direction_total = 0
    for r in dir_records:
        try:
            pred_change = float(r["predicted_close"]) - float(r["current_price"])
            actual_change = float(r["actual_close"]) - float(r["current_price"])
            if abs(pred_change) > 0.15 or abs(actual_change) > 0.15:
                direction_total += 1
                if (pred_change > 0 and actual_change > 0) or (pred_change < 0 and actual_change < 0):
                    direction_correct += 1
        except (KeyError, ValueError, TypeError):
            continue

    # 手动回填的方向准确率
    manual = [r for r in valid if r.get("backfill_type") == "manual"
              and r.get("predicted_close") and r.get("current_price")]
    manual_dir_correct = 0
    manual_dir_total = 0
    for r in manual:
        try:
            pred_change = float(r["predicted_close"]) - float(r["current_price"])
            actual_change = float(r["actual_close"]) - float(r["current_price"])
            if abs(pred_change) > 0.15 or abs(actual_change) > 0.15:
                manual_dir_total += 1
                if (pred_change > 0 and actual_change > 0) or (pred_change < 0 and actual_change < 0):
                    manual_dir_correct += 1
        except (KeyError, ValueError, TypeError):
            continue

    # 区间命中
    in_range = 0
    for r in valid:
        try:
            lo = float(r.get("predicted_low", 0))
            hi = float(r.get("predicted_high", 0))
            ac = float(r.get("actual_close", 0))
            if lo <= ac <= hi:
                in_range += 1
        except (KeyError, ValueError, TypeError):
            continue

    return {
        "status": "ok",
        "count": len(valid),
        "total_predictions": len(records),
        "filtered_outliers": filtered_count,
        "mae": round(statistics.mean(abs_errors), 2),
        "rmse": round(statistics.mean([e**2 for e in errors])**0.5, 2),
        "mean_bias": round(statistics.mean(errors), 2),
        "direction_accuracy": round(direction_correct / max(direction_total, 1) * 100, 1),
        "direction_total": direction_total,
        "manual_direction_accuracy": round(manual_dir_correct / max(manual_dir_total, 1) * 100, 1) if manual_dir_total >= 3 else None,
        "manual_direction_total": manual_dir_total,
        "in_range_pct": round(in_range / len(valid) * 100, 1),
    }


def get_calibration(stock_code: str) -> dict:
    """获取校准参数——用于修正后续预测。"""
    stats = compute_accuracy(stock_code)
    if stats["status"] != "ok":
        return {"bias_correction": 0.0, "range_multiplier": 1.0, "ready": False}

    # 中位数偏差 + 指数加权（排除异常值）
    records = _load_records(stock_code)
    filled = [r for r in records if r.get("actual_close") and abs(float(r.get("error", 0))) < 5.0]
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

    # 区间宽度自适应（目标：95%命中率）
    in_range = stats["in_range_pct"]
    range_mult = 1.0
    if in_range < 70:
        range_mult = 1.6
    elif in_range < 80:
        range_mult = 1.40
    elif in_range < 85:
        range_mult = 1.25
    elif in_range < 90:
        range_mult = 1.15
    elif in_range < 93:
        range_mult = 1.08
    elif in_range < 95:
        range_mult = 1.03  # 接近目标，微扩
    elif in_range >= 99:
        range_mult = 0.88
    elif in_range >= 98:
        range_mult = 0.92
    elif in_range >= 96:
        range_mult = 0.96
    else:  # 95-96%
        range_mult = 1.0  # 达标，保持

    # 连续命中奖励（仅当命中率已达标时适度收窄）
    if in_range >= 95 and consecutive >= 10:
        range_mult *= 0.90
    elif in_range >= 95 and consecutive >= 5:
        range_mult *= 0.95
    elif in_range >= 90 and consecutive >= 15:
        range_mult *= 0.85  # 长期连续命中才收窄

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
    _ensure_tracker_dir()
    with open(_records_path(stock_code), "w") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
