"""自动备份守护——收盘后快照关键文件，支持恢复。

用法:
    python cli/backup.py              # 执行备份
    python cli/backup.py --restore    # 从最新备份恢复
    python cli/backup.py --list       # 列出所有备份
"""

import os
import shutil
import sys
import io
from datetime import date, datetime, timedelta
from pathlib import Path


def _fix_encoding() -> None:
    """Windows GBK 编码修复——仅在直接运行时调用。"""
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BACKUP_ROOT = Path(".claude/backups")
MAX_DAYS = 7

# 需要备份的文件清单：(源路径, 是否为目录)
BACKUP_ITEMS = [
    (Path(".claude/scheduled_tasks.json"), False),
    (Path("CLAUDE.md"), False),
    (Path(".position_history"), True),
    (Path(".prediction_history"), True),
    (Path("REVIEW.md"), False),
]


def backup(today: date | None = None) -> Path:
    """执行备份——复制关键文件到 .claude/backups/YYYY-MM-DD/。"""
    if today is None:
        today = date.today()

    dest_dir = BACKUP_ROOT / today.strftime("%Y-%m-%d")
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    backed = 0
    skipped = 0

    for src, is_dir in BACKUP_ITEMS:
        if not src.exists():
            skipped += 1
            continue

        dest = dest_dir / src.name
        try:
            if is_dir:
                shutil.copytree(src, dest)
            else:
                shutil.copy2(src, dest)
            backed += 1
        except Exception as e:
            print(f"  备份失败 {src}: {e}")

    print(f"  备份完成: {backed} 个文件 → {dest_dir}")
    print(f"  跳过: {skipped} 个（不存在）")

    # 清理过期备份
    _cleanup_old(today)

    # 自动 push
    _auto_push()

    return dest_dir


def _cleanup_old(today: date) -> None:
    """清理超过 7 天的旧备份。"""
    cutoff = today - timedelta(days=MAX_DAYS)
    for d in BACKUP_ROOT.iterdir():
        if d.is_dir():
            try:
                d_date = date.fromisoformat(d.name)
                if d_date < cutoff:
                    shutil.rmtree(d)
                    print(f"  清理旧备份: {d.name}")
            except ValueError:
                pass


def _auto_push() -> None:
    """自动 git push 备份文件。"""
    import subprocess
    try:
        subprocess.run(
            ["git", "add", ".claude/backups/"],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "-m", f"backup: {date.today()} snapshot"],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "push"],
            capture_output=True, timeout=30,
        )
        print("  git push 完成")
    except Exception as e:
        print(f"  git push 跳过: {e}")


def restore() -> bool:
    """从最新备份恢复所有关键文件。"""
    if not BACKUP_ROOT.exists():
        print("  没有找到备份目录")
        return False

    backups = sorted(
        [d for d in BACKUP_ROOT.iterdir() if d.is_dir()],
        reverse=True,
    )
    if not backups:
        print("  没有找到任何备份")
        return False

    latest = backups[0]
    print(f"  从 {latest.name} 恢复...")

    restored = 0
    for src_name in [item[0].name for item in BACKUP_ITEMS]:
        backup_src = latest / src_name
        dest = Path(src_name)
        if not backup_src.exists():
            continue
        try:
            if backup_src.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(backup_src, dest)
            else:
                shutil.copy2(backup_src, dest)
            restored += 1
            print(f"  ✅ {src_name}")
        except Exception as e:
            print(f"  ❌ {src_name}: {e}")

    print(f"  恢复完成: {restored} 个文件")
    return restored > 0


def list_backups() -> None:
    """列出所有备份。"""
    if not BACKUP_ROOT.exists():
        print("  没有备份")
        return
    for d in sorted(BACKUP_ROOT.iterdir(), reverse=True):
        if d.is_dir():
            size = sum(
                f.stat().st_size
                for f in d.rglob("*")
                if f.is_file()
            )
            print(f"  {d.name}  ({size / 1024:.0f} KB)")


if __name__ == "__main__":
    _fix_encoding()
    if "--restore" in sys.argv:
        restore()
    elif "--list" in sys.argv:
        list_backups()
    else:
        print(f"=== 收盘备份 === {date.today()}")
        backup()
