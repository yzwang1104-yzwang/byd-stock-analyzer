"""Shanghai Index Predictor V2.

V1 issues: stale data, forced direction on tie, no V-reversal, no archive.
V2 fixes: real-time API, flat on tie, V-reversal +8, support detection +10, auto-archive.
6/29 post-mortem: missed 3.00 triple-test support -> added low5/low20 overlap check.
"""

import json
import urllib.request as URL
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

HISTORY_FILE = Path(".prediction_history/sh_index_predictions.json")


def _fetch_realtime() -> Optional[dict]:
    """Fetch real-time SH50 ETF + SH Index quotes from Tencent."""
    try:
        url = "http://qt.gtimg.cn/q=sh510050,sh000001"
        data = URL.urlopen(url, timeout=10).read().decode("gbk")
        result = {}
        for line in data.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("~")
            if "sh510050" in line:
                result["etf_price"] = float(parts[3])
                result["etf_prev"] = float(parts[4])
                result["etf_chg"] = (result["etf_price"] - result["etf_prev"]) / result["etf_prev"] * 100
            elif "sh000001" in line:
                result["index"] = float(parts[3])
                result["index_prev"] = float(parts[4])
                result["index_chg"] = (result["index"] - result["index_prev"]) / result["index_prev"] * 100
        return result if result else None
    except Exception:
        return None


def predict() -> dict:
    """Predict SH Index direction. Returns dict with direction, confidence, score, factors."""
    rt = _fetch_realtime()

    try:
        df = pd.read_csv(".cache/prices_510050.csv", index_col=0, parse_dates=True)
        cl = df["close"]
    except Exception:
        return {"direction": "unknown", "confidence": 0, "error": "no history"}

    p = cl.iloc[-1]
    if rt:
        p = rt["etf_price"]

    m5 = cl.rolling(5).mean().iloc[-1]
    m10 = cl.rolling(10).mean().iloc[-1]
    m20 = cl.rolling(20).mean().iloc[-1]
    m50 = cl.rolling(50).mean().iloc[-1]

    delta = cl.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rs0 = rsi.iloc[-1]

    mom5 = (p - cl.iloc[-6]) / cl.iloc[-6] * 100

    score = 0

    # MA alignment (25 pts)
    if p > m5: score += 5
    else: score -= 5
    if m5 > m10: score += 5
    else: score -= 5
    if m10 > m20: score += 5
    else: score -= 5
    if m20 > m50: score += 10
    else: score -= 10

    # RSI (15 pts)
    if rs0 > 60: score += 8
    elif rs0 >= 45: score += 0
    elif rs0 >= 30: score -= 8
    else: score += 12

    # Momentum (15 pts)
    if mom5 > 1.5: score += 8
    elif mom5 > 0.3: score += 4
    elif mom5 > -0.3: score += 0
    elif mom5 > -1.5: score -= 4
    else: score -= 8

    # V-reversal detection (10 pts)
    rt_chg = rt.get("etf_chg", 0) if rt else 0
    if rt_chg < -1.5:
        score += 8

    # Support confirmation (10 pts) - 6/29 lesson
    low5 = cl.iloc[-5:].min()
    low20 = cl.iloc[-20:].min()
    if abs(low5 - low20) / low20 < 0.01:
        score += 10

    # Decide
    if score >= 5:
        direction = "up"
        confidence = min(85, 50 + abs(score))
    elif score <= -5:
        direction = "down"
        confidence = min(85, 50 + abs(score))
    else:
        direction = "flat"
        confidence = 50 - abs(score)

    labels = {"up": "U", "down": "D", "flat": "F", "unknown": "?"}

    result = {
        "timestamp": datetime.now().isoformat(),
        "date": date.today().isoformat(),
        "direction": direction,
        "confidence": confidence,
        "score": score,
        "label": labels[direction],
        "factors": {
            "price": round(p, 2),
            "ma5": round(m5, 2),
            "ma20": round(m20, 2),
            "ma50": round(m50, 2),
            "rsi": round(rs0, 1),
            "mom5": round(mom5, 2),
            "intraday_chg": round(rt_chg, 2) if rt else None,
            "support_confirm": abs(low5 - low20) / low20 < 0.01,
        },
    }

    _archive(result)
    return result


def _archive(result: dict) -> None:
    """Save prediction to history file."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    records = []
    if HISTORY_FILE.exists():
        try:
            records = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    records.append({
        "id": len(records) + 1,
        "ts": result["timestamp"],
        "direction": result["direction"],
        "confidence": result["confidence"],
        "score": result["score"],
        "actual": None,
    })
    HISTORY_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def verify(actual_change: float) -> dict:
    """Verify latest prediction against actual market change."""
    if not HISTORY_FILE.exists():
        return {"status": "no_predictions"}
    records = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    if not records:
        return {"status": "no_predictions"}
    last = records[-1]
    if last.get("actual") is not None:
        return {"status": "already_verified"}
    actual_dir = "up" if actual_change > 0 else ("down" if actual_change < 0 else "flat")
    correct = last["direction"] == actual_dir
    last["actual"] = actual_change
    last["actual_dir"] = actual_dir
    last["correct"] = correct
    HISTORY_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    verified = [r for r in records if r.get("correct") is not None]
    total = len(verified)
    correct_count = sum(1 for r in verified if r["correct"])
    acc = round(correct_count / total * 100, 1) if total > 0 else 0
    return {
        "status": "ok",
        "predicted": last["direction"],
        "actual": actual_dir,
        "correct": correct,
        "total_predictions": total,
        "accuracy": acc,
    }
