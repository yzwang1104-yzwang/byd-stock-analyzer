"""每日汇总——查看当天所有定时分析结果。"""
import json
from datetime import date
from pathlib import Path

LOG_FILE = Path(".prediction_history/daily_log.txt")
RECORDS_FILE = Path(".prediction_history/predictions_002594.json")


def show():
    today = date.today().isoformat()

    # 预测记录
    if RECORDS_FILE.exists():
        records = json.load(open(RECORDS_FILE))
        today_records = [r for r in records if r["date"] == today]
        if today_records:
            print(f"=== {today} 比亚迪预测记录 ({len(today_records)} 次) ===\n")
            for r in today_records:
                actual = r.get("actual_close") or "待回填"
                err = r.get("error") or "-"
                print(
                    f"  #{r['id']} {r['timestamp'][:16]}  "
                    f"预测: {r['predicted_close']}  "
                    f"区间: [{r['predicted_low']}-{r['predicted_high']}]  "
                    f"实际: {actual}  误差: {err}"
                )
        else:
            print(f"=== {today} 暂无预测记录 ===\n")
    else:
        print("无预测记录")

    # 日志
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        today_lines = [l for l in lines if today in l or "评分" in l or "预测" in l or "BUY" in l or "SELL" in l or "WAIT" in l]
        if today_lines:
            print(f"\n=== 日志摘要 ===\n")
            for l in today_lines[-30:]:
                print(f"  {l[:120]}")


if __name__ == "__main__":
    show()
