"""会话启动检查——每次对话开始时自动执行 4 项检查。"""
import os
import sys
import io
from datetime import date, datetime
from pathlib import Path

# Ensure project root is in path (for standalone execution)
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _fix_encoding() -> None:
    """Windows GBK 编码修复——仅在直接运行时调用。"""
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def check_git_status() -> dict:
    """检查 git 工作区状态。"""
    import subprocess
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        dirty = [line for line in r.stdout.split("\n") if line.strip()]
        return {
            "ok": len(dirty) == 0,
            "dirty_files": len(dirty),
            "detail": dirty[:10] if dirty else [],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_claude_md() -> dict:
    """检查 CLAUDE.md 最后更新时间。"""
    path = Path("CLAUDE.md")
    if not path.exists():
        return {"ok": False, "error": "CLAUDE.md 不存在！"}
    mtime = path.stat().st_mtime
    last_mod = datetime.fromtimestamp(mtime)
    days_ago = (datetime.now() - last_mod).days
    return {
        "ok": days_ago <= 2,
        "last_modified": last_mod.strftime("%Y-%m-%d %H:%M"),
        "days_ago": days_ago,
    }


def check_positions() -> dict:
    """检查持仓文件完整性。"""
    pos_dir = Path(".position_history")
    if not pos_dir.exists():
        return {"ok": True, "files": 0, "note": "无持仓目录（可能无持仓）"}
    files = list(pos_dir.glob("*.json"))
    return {
        "ok": len(files) > 0,
        "files": len(files),
        "stocks": [f.stem for f in files],
    }


def check_prediction_history() -> dict:
    """检查预测历史文件。"""
    pred_dir = Path(".prediction_history")
    if not pred_dir.exists():
        return {"ok": False, "error": "预测历史目录不存在"}
    files = list(pred_dir.glob("predictions_*.json"))
    total = 0
    for f in files:
        import json
        try:
            records = json.loads(f.read_text())
            total += len(records)
        except Exception:
            pass
    return {
        "ok": len(files) > 0,
        "files": len(files),
        "total_records": total,
    }


def run():
    """执行所有检查并输出报告。"""
    from core.trading_calendar import is_trading_day

    today = date.today()
    is_td, reason = is_trading_day(today)

    print()
    print("=" * 60)
    print(f"  会话启动检查 — {today}")
    print("=" * 60)
    print()

    # 0. 交易日检查（最优先）
    if not is_td:
        print(f"  🔴 今日休市: {reason}")
        print("  ⏸  跳过所有股票监控任务")
        print("=" * 60)
        return False  # 返回 False 表示非交易日
    else:
        print(f"  🟢 交易日 — {reason}")
    print()

    all_ok = True

    # 1. Git status
    git = check_git_status()
    if git["ok"]:
        print("  ✅ Git 工作区干净")
    else:
        all_ok = False
        if "error" in git:
            print(f"  ⚠ Git 检查失败: {git['error']}")
        else:
            print(f"  ⚠ Git 有 {git['dirty_files']} 个未提交文件:")
            for f in git["detail"]:
                print(f"      {f}")

    # 2. CLAUDE.md
    cm = check_claude_md()
    if cm["ok"]:
        print(f"  ✅ CLAUDE.md 最后更新: {cm['last_modified']}")
    else:
        all_ok = False
        if "error" in cm:
            print(f"  🔴 {cm['error']}")
        else:
            print(f"  ⚠ CLAUDE.md {cm['days_ago']}天未更新")

    # 3. 持仓
    pos = check_positions()
    if pos["ok"]:
        print(f"  ✅ 持仓文件: {pos['files']} 个 ({', '.join(pos['stocks'])})")
    else:
        print(f"  ⚠ 持仓: {pos.get('note', '无文件')}")

    # 4. 预测历史
    pred = check_prediction_history()
    if pred["ok"]:
        print(f"  ✅ 预测记录: {pred['files']} 个文件, {pred['total_records']} 条")
    else:
        all_ok = False
        print(f"  ⚠ 预测历史: {pred.get('error', '未知问题')}")

    print()
    if all_ok:
        print("  🟢 全部通过")
    else:
        print("  🟡 有告警项，建议检查后再操作")
    print("=" * 60)
    print()

    return all_ok


if __name__ == "__main__":
    _fix_encoding()
    ok = run()
    sys.exit(0 if ok else 1)
