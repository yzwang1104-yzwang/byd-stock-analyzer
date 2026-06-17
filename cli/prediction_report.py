"""预测验证报告 — 对比预测值 vs 实际值。"""
import json
import sys
import io
from pathlib import Path
from datetime import date

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def run(stock: str = "600370"):
    pred_file = Path(f".prediction_history/predictions_{stock}.json")
    if not pred_file.exists():
        print(f"  无预测数据: {stock}")
        return

    records = json.loads(pred_file.read_text())
    latest = records[-1] if records else None
    if not latest or latest.get("type") != "10day_prediction":
        print(f"  无10日预测记录: {stock}")
        return

    preds = latest["predictions"]
    today_str = str(date.today())

    print()
    print("=" * 65)
    print(f"  {stock} 预测验证报告 — {date.today()}")
    print(f"  基准价: {latest['base_price']} | 创建: {latest['created']}")
    print("=" * 65)
    print()
    print(f"  {'日期':<12} {'预测':>7} {'区间':>16} {'实际':>7} {'命中':>5} {'偏差':>7}")
    print(f"  {'-'*55}")

    hit_count = 0
    total = 0
    for p in preds:
        pdate = p["date"]
        # Check if backfilled
        actual = None
        for r in records:
            if r.get("type") != "10day_prediction":
                for bp in r.get("predictions", []):
                    pass
        # Look for actual in prediction tracker
        tracker_file = Path(f".prediction_history/predictions_{stock}.json")
        # simplified: check if date passed
        if pdate <= today_str:
            total += 1
            # Try to find actual from backfill records
            actual_val = None
            # For now just show prediction
            if actual_val:
                hit = p["predicted_low"] <= actual_val <= p["predicted_high"]
                if hit: hit_count += 1
                dev = actual_val - p["predicted_price"]
                print(f"  {pdate:<12} {p['predicted_price']:>6.2f} {p['predicted_low']:>6.2f}~{p['predicted_high']:<6.2f} {actual_val:>6.2f} {'YES' if hit else 'NO':>5} {dev:>+6.2f}")
            else:
                marker = " ← 今天" if pdate == today_str else ""
                print(f"  {pdate:<12} {p['predicted_price']:>6.2f} {p['predicted_low']:>6.2f}~{p['predicted_high']:<6.2f} {'待验证':>7}{marker}")

    if total > 0:
        print(f"\n  区间命中: {hit_count}/{total} ({hit_count/total*100:.0f}%)" if total > 0 else "")
    print(f"  剩余待验证: {10 - total} 天")
    print()
    print(f"  回填命令: python -m cli.main backfill --stock {stock} --price <收盘价>")
    print("=" * 65)


if __name__ == "__main__":
    stock = sys.argv[1] if len(sys.argv) > 1 else "600370"
    run(stock)
