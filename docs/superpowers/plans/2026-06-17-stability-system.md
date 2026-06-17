# 系统稳定性实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立两层防护体系——Git 纪律防止代码丢失，自动备份守护防止配置/数据丢失。

**Architecture:** 
- 方案 A：CLAUDE.md 新增稳定性约定章节 + 会话启动自动执行 4 项检查
- 方案 B：`cli/backup.py` 脚本 + 1 个 cron 任务实现收盘自动备份

**Tech Stack:** Python 3.12 + shutil + json + Cron

**Design Doc:** `docs/superpowers/specs/2026-06-17-stability-system-design.md`

---

## 文件职责

| 文件 | 职责 |
|------|------|
| `CLAUDE.md`（修改） | 新增「十、系统稳定性约定」——Git 纪律 + 会话启动清单 |
| `cli/startup_check.py`（新建） | 每次会话启动时执行 4 项检查，输出状态报告 |
| `cli/backup.py`（新建） | 收盘备份：快照关键文件到 `.claude/backups/`；支持 `--restore` 恢复 |
| `memory/cron-tasks-2026-06-17.md`（修改） | cron 清单加第 10 个任务 |

---

### Task 1: CLAUDE.md — 新增稳定性约定章节

**Files:**
- Modify: `CLAUDE.md`（末尾追加）

- [ ] **Step 1: 在 CLAUDE.md 末尾追加「十、系统稳定性约定」**

在文件末尾追加以下内容：

```markdown

---

## 十、系统稳定性约定（2026-06-17 生效）

### Git 纪律

| 类型 | 规则 |
|------|------|
| 🚫 禁止 | `git reset --hard`（除非用户明确说"覆盖本地"） |
| 🚫 禁止 | `git clean -fd`（同上） |
| 🚫 禁止 | 覆盖 CLAUDE.md 已有内容（只追加，不替换已有章节） |
| 🚫 禁止 | 删除 `.claude/` 目录下的任何文件 |
| ✅ 必须 | 每次代码改动后 `git commit` |
| ✅ 必须 | 每次会话结束前 `git push` |
| ✅ 必须 | 每天打 `stable-YYYY-MM-DD` tag |
| ✅ 必须 | CLAUDE.md 改动视为代码改动，必须 commit |
| ✅ 必须 | cron 任务清单同步写入 `memory/cron-tasks-*.md` |

### 会话启动检查清单

每次对话开始时自动执行（`python cli/startup_check.py`）：
1. `git status` — 未提交改动告警
2. `CronList` — 定时任务是否都在
3. `.position_history/` — 持仓文件完整性
4. CLAUDE.md 版本 — 最后更新时间戳

### 备份恢复

```bash
python cli/backup.py --restore   # 从最新备份恢复所有关键文件
# 备份位置: .claude/backups/YYYY-MM-DD/
# 触发时间: 交易日 15:05 自动执行
```
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "feat: add stability conventions — Git discipline + session checklist"
```

---

### Task 2: 会话启动检查脚本

**Files:**
- Create: `cli/startup_check.py`

- [ ] **Step 1: 创建 startup_check.py**

```python
"""会话启动检查——每次对话开始时自动执行 4 项检查。"""
import os
import sys
import io
from datetime import date
from pathlib import Path

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
    from datetime import datetime
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
    print()
    print("=" * 60)
    print(f"  会话启动检查 — {date.today()}")
    print("=" * 60)
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
    ok = run()
    sys.exit(0 if ok else 1)
```

- [ ] **Step 2: 运行验证**

```bash
python cli/startup_check.py
```

预期输出：4 项检查结果（Git/CLAUDE.md/持仓/预测）。

- [ ] **Step 3: Commit**

```bash
git add cli/startup_check.py
git commit -m "feat: add session startup check script — 4-point health check"
```

---

### Task 3: 自动备份守护脚本

**Files:**
- Create: `cli/backup.py`

- [ ] **Step 1: 创建 backup.py**

```python
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
    if "--restore" in sys.argv:
        restore()
    elif "--list" in sys.argv:
        list_backups()
    else:
        print(f"=== 收盘备份 === {date.today()}")
        backup()
```

- [ ] **Step 2: 运行验证**

```bash
python cli/backup.py                     # 执行备份
python cli/backup.py --list              # 列出备份
ls .claude/backups/$(date +%Y-%m-%d)/    # 核对文件
```

预期：`.claude/backups/2026-06-17/` 下出现 `scheduled_tasks.json`、`CLAUDE.md`、`position_history/`、`prediction_history/`。

- [ ] **Step 3: Commit**

```bash
git add cli/backup.py
git commit -m "feat: add auto-backup daemon — daily snapshot + restore"
```

---

### Task 4: 新增收盘备份 Cron 任务

**Files:**
- Modify: `memory/cron-tasks-2026-06-17.md`（追加第 10 个任务）

- [ ] **Step 1: 创建 Cron 任务**

```
交易日 15:05 — 收盘备份:
  cd /c/Users/Administrator/byd-stock-analyzer && python cli/backup.py
```

- [ ] **Step 2: 更新 cron 清单 memory 文件**

在 `memory/cron-tasks-2026-06-17.md` 末尾追加第 10 个任务。

- [ ] **Step 3: Commit**

```bash
git commit -m "cron: add daily 15:05 backup task"
```

---

### Task 5: 端到端验证

- [ ] **Step 1: 模拟灾难恢复**

```bash
# 1. 先做一次备份
python cli/backup.py

# 2. 模拟文件丢失
mv .position_history .position_history_bak

# 3. 从备份恢复
python cli/backup.py --restore

# 4. 验证
ls .position_history/

# 5. 清理
rm -rf .position_history_bak
```

- [ ] **Step 2: 验证 startup check**

```bash
python cli/startup_check.py
```

预期：4 项全部通过。

- [ ] **Step 3: 打稳定标签**

```bash
git tag "stable-$(date +%Y-%m-%d)"
git push --tags
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: stable-2026-06-17 — stability system live"
git push
git push --tags
```
