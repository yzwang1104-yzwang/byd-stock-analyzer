# 系统稳定性方案 — Git 纪律 + 自动备份守护

**日期:** 2026-06-17
**状态:** 已批准
**背景:** 多次发生代码/配置/数据丢失（git reset、cron 任务消失、CLAUDE.md 被覆盖），需要系统性解决。

---

## 方案 A：Git 纪律

### 硬约束

| 类型 | 规则 |
|------|------|
| 🚫 禁止 | `git reset --hard`（除非用户明确说"覆盖本地"） |
| 🚫 禁止 | `git clean -fd`（同上） |
| 🚫 禁止 | 覆盖 CLAUDE.md 已有内容（只追加，不替换） |
| 🚫 禁止 | 删除 `.claude/` 目录下的任何文件 |
| ✅ 必须 | 每次代码改动后 `git commit` |
| ✅ 必须 | 每次会话结束前 `git push` |
| ✅ 必须 | 每天打 `stable-YYYY-MM-DD` tag |
| ✅ 必须 | CLAUDE.md 改动视为代码改动，必须 commit |
| ✅ 必须 | cron 任务清单同步写入 `memory/cron-tasks-*.md` |

### 会话启动检查清单

每次对话开头自动执行：
1. `git status` — 检查未提交改动
2. `CronList` — 检查定时任务是否都在
3. 持仓文件 — 检查 `.position_history/` 完整性
4. 比对 CLAUDE.md — 版本号/时间戳是否最新

### 落地点

CLAUDE.md 新增 `## 十、系统稳定性约定` 章节。

---

## 方案 B：自动备份守护

### 备份内容

| 文件 | 路径 | 优先级 |
|------|------|:--:|
| 定时任务 | `.claude/scheduled_tasks.json` | P0 |
| 项目记录 | `CLAUDE.md` | P0 |
| 持仓数据 | `.position_history/*.json` | P0 |
| 预测记录 | `.prediction_history/*.json` | P1 |
| 审查报告 | `REVIEW.md` | P2 |

### 备份策略

- **触发时间:** 交易日 15:05（收盘后 5 分钟）
- **存储位置:** `.claude/backups/YYYY-MM-DD/`
- **保留天数:** 7 天滚动
- **操作:** 完整快照 → 自动 git push

### 恢复命令

```bash
python cli/backup.py --restore  # 从最新备份恢复所有关键文件
```

### 实现

新增 `cli/backup.py`（约 80 行），新增 1 个 cron 任务。

### Cron 扩展

在现有 9 个任务基础上增加：
- `交易日 15:05` — 收盘备份

---

## 验收标准

1. ✅ 会话开启时自动执行 4 项检查
2. ✅ `git reset --hard` 后 `cli/backup.py --restore` 可恢复所有关键文件
3. ✅ 每天 15:05 自动备份成功，保留 7 天
4. ✅ CLAUDE.md 不被覆盖，只被追加
