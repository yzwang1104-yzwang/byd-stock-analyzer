"""大盘方向预测 + 自动验证 + 权重自校准。"""

import json
import statistics
from datetime import date
from pathlib import Path

from core.data_fetcher import fetch_price_history

PRED_DIR = Path(".prediction_history")
INDICES = {
    "510050": "上证50", "510300": "沪深300",
    "159915": "创业板", "512100": "中证1000",
}


def predict_market(days: int = 250) -> dict:
    """预测今天大盘涨跌。返回评分+预判+各指数明细。"""
    results = {}
    today = date.today().isoformat()

    for code, name in INDICES.items():
        p = fetch_price_history(code, days=days + 5, force_refresh=True)
        closes = [b.close for b in p]
        volumes = [b.volume for b in p]
        n = len(closes)

        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20
        ma60 = sum(closes[-60:]) / 60 if n >= 60 else ma20
        ma120 = sum(closes[-120:]) / 120 if n >= 120 else ma60
        ma250 = sum(closes[-250:]) / 250 if n >= 250 else ma120

        chg_5 = statistics.mean(
            [(closes[i] - closes[i - 1]) / closes[i - 1] * 100 for i in range(max(-5, -n + 1), 0)]
        )
        chg_20 = statistics.mean(
            [(closes[i] - closes[i - 1]) / closes[i - 1] * 100 for i in range(max(-20, -n + 1), 0)]
        )
        chg_60 = statistics.mean(
            [(closes[i] - closes[i - 1]) / closes[i - 1] * 100 for i in range(max(-60, -n + 1), 0)]
        )

        vol_ratio = (
            statistics.mean(volumes[-5:]) / statistics.mean(volumes[-60:])
            if len(volumes) >= 60
            else 1.0
        )

        high_250 = max(closes[-250:]) if n >= 250 else max(closes)
        low_250 = min(closes[-250:]) if n >= 250 else min(closes)
        position = (closes[-1] - low_250) / (high_250 - low_250) * 100 if high_250 > low_250 else 50

        # 加载自校准权重
        weights = _load_weights()

        score = 50
        if ma5 > ma10: score += weights.get("ma_short", 5)
        if ma10 > ma20: score += weights.get("ma_mid", 5)
        if ma20 > ma60: score += weights.get("ma_long", 8)
        if ma60 > ma120: score += weights.get("ma_vlong", 7)
        if chg_5 > 0: score += weights.get("mom_5d", 8)
        if chg_20 > 0: score += weights.get("mom_20d", 7)
        if chg_60 > 0: score += weights.get("mom_60d", 5)
        if vol_ratio > 1.1: score += weights.get("volume", 5)
        if position < 30: score += weights.get("oversold", 5)

        direction = "涨" if score > 55 else ("跌" if score < 45 else "震荡")
        results[code] = {
            "name": name, "close": closes[-1], "score": score,
            "direction": direction, "position": round(position, 1),
            "ma5": round(ma5, 2), "ma20": round(ma20, 2),
            "ma60": round(ma60, 2), "chg_5d": round(chg_5, 2),
        }

    scores = [r["score"] for r in results.values()]
    composite = round(sum(scores) / len(scores))

    prediction = {
        "date": today,
        "indices": results,
        "composite_score": composite,
        "prediction": "涨" if composite > 55 else ("跌" if composite < 45 else "震荡"),
    }

    # 保存预测
    pred_file = PRED_DIR / f"market_prediction_{today}.json"
    pred_file.write_text(json.dumps(prediction, ensure_ascii=False, indent=2))

    return prediction


def verify_prediction(pred_date: str | None = None) -> dict:
    """用实际收盘数据验证预测。pred_date=None=验证最近一次。"""
    if pred_date is None:
        files = sorted(PRED_DIR.glob("market_prediction_*.json"))
        if not files:
            return {"status": "no_prediction"}
        pred = json.loads(files[-1].read_text())
    else:
        pred_file = PRED_DIR / f"market_prediction_{pred_date}.json"
        if not pred_file.exists():
            return {"status": "not_found"}
        pred = json.loads(pred_file.read_text())

    if pred.get("actual"):
        return {"status": "already_verified", "prediction": pred}

    # 获取实际数据
    correct_count = 0
    total = 0
    actuals = {}

    for code, info in pred["indices"].items():
        try:
            p = fetch_price_history(code, days=2, force_refresh=True)
            actual_close = p[-1].close
            prev_close = p[-2].close if len(p) >= 2 else actual_close
            actual_dir = "涨" if actual_close > prev_close else ("跌" if actual_close < prev_close else "平")
            predicted_dir = info["direction"]

            actuals[code] = {
                "name": info["name"],
                "close": actual_close,
                "direction": actual_dir,
                "predicted": predicted_dir,
                "correct": predicted_dir == actual_dir or (predicted_dir == "震荡"),
            }
            if actuals[code]["correct"]:
                correct_count += 1
            total += 1
        except Exception as e:
            actuals[code] = {"name": info["name"], "error": str(e)[:50]}

    accuracy = round(correct_count / total * 100, 1) if total > 0 else 0

    # 更新预测文件
    pred["actual"] = actuals
    pred["accuracy"] = accuracy
    pred["correct_count"] = correct_count
    pred["total"] = total

    pred_file = PRED_DIR / f"market_prediction_{pred['date']}.json"
    pred_file.write_text(json.dumps(pred, ensure_ascii=False, indent=2))

    # 自校准权重
    _calibrate_weights(accuracy, pred)

    return {"status": "verified", "accuracy": accuracy, "correct": correct_count, "total": total}


def _load_weights() -> dict:
    """加载自校准权重。"""
    wf = PRED_DIR / "market_weights.json"
    if wf.exists():
        return json.loads(wf.read_text())
    return {
        "ma_short": 5, "ma_mid": 5, "ma_long": 8, "ma_vlong": 7,
        "mom_5d": 8, "mom_20d": 7, "mom_60d": 5,
        "volume": 5, "oversold": 5,
    }


def _calibrate_weights(accuracy: float, pred: dict) -> None:
    """基于预测准确率自校准权重。准确率高→加大有效因子权重。"""
    weights = _load_weights()
    if accuracy >= 80:
        return  # 已很好，不调整
    elif accuracy < 50:
        # 表现差，随机微调探索
        import random
        for k in weights:
            weights[k] = max(2, min(15, weights[k] + random.randint(-2, 2)))
    else:
        # 50-80%，微调
        delta = 1 if accuracy < 65 else -1
        for k in ["ma_long", "ma_vlong", "mom_5d", "mom_20d"]:
            weights[k] = max(2, min(15, weights[k] + delta))

    wf = PRED_DIR / "market_weights.json"
    wf.write_text(json.dumps(weights, ensure_ascii=False, indent=2))
