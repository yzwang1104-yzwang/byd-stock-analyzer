"""上证指数预测回填 — 收盘后运行以验证下午预测准确率。"""
import json
import sys
import io
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def backfill(close_price: float):
    file = Path(".prediction_history/sh_index_predictions.json")
    if not file.exists():
        print("  无预测记录")
        return

    records = json.loads(file.read_text())
    unverified = [r for r in records if not r.get("verified") and r.get("actual_close") is None]

    if not unverified:
        print("  所有预测已验证")
        return

    # 回填最新一条
    r = unverified[-1]
    pred = r["predicted_close"]
    low = r["confidence_68_low"]
    high = r["confidence_68_high"]
    in_range = low <= close_price <= high
    error = close_price - pred

    r["actual_close"] = round(close_price, 2)
    r["error"] = round(error, 2)
    r["in_range"] = in_range
    r["verified"] = True
    r["verified_at"] = datetime.now().isoformat()

    file.write_text(json.dumps(records, ensure_ascii=False, indent=2))

    # 统计
    verified = [r for r in records if r.get("verified")]
    in_range_count = sum(1 for r in verified if r.get("in_range"))
    errors = [abs(r["error"]) for r in verified]

    print()
    print("=" * 55)
    print(f"  上证预测回填完成")
    print(f"  预测: {pred} | 实际: {close_price} | 误差: {error:+.2f}")
    print(f"  68%区间: {low}~{high} | {'✅ 命中' if in_range else '❌ 未命中'}")
    print()
    print(f"  累计: {len(verified)} 次预测")
    print(f"  区间命中: {in_range_count}/{len(verified)} ({in_range_count/len(verified)*100:.1f}%)")
    print(f"  平均误差: {sum(errors)/len(errors):.2f} 点")
    print("=" * 55)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--close":
        backfill(float(sys.argv[2]))
    else:
        print("用法: python cli/backfill_sh.py --close <收盘指数>")
