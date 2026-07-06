# Sell Alert 卖出提醒 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `cli/sell_alert.py`，对"低点买入"持仓股在价格回弹至历史最高 45%-70% 时表格化卖出提醒。

**Architecture:** 独立脚本对标 `cli/buy_alert.py`，复用 `core/data_fetcher.py`（实时行情 + 全量 K 线）和 `core/position_manager.py`（持仓均价），零修改现有模块。新增 1 个持久化 Cron 任务。

**Tech Stack:** Python + core/ 模块 + 腾讯实时 API + Cron

---

## File Structure

| 文件 | 动作 | 职责 |
|------|:--:|------|
| `cli/sell_alert.py` | **新建** | 卖出提醒主逻辑——扫描持仓、判断条件、表格输出 |
| `tests/test_sell_alert.py` | **新建** | 单元测试——条件判断、边界情况 |
| Cron (持久化) | **+1** | 交易日 09:30/11:00/14:00/14:50 自动触发 |

---

### Task 1: 创建 sell_alert.py 核心脚本

**Files:**
- Create: `cli/sell_alert.py`

- [ ] **Step 1: 写完整的 sell_alert.py**

```python
"""卖出提醒 — 低点买入持仓在价格回弹至历史最高 45%-70% 时告警。

触发条件（必须同时满足）：
  1. 低点买入：持仓均价 ≤ 历史最低价 × 1.15
  2. 目标区间：high_all × 45% ≤ 当前实时价 ≤ high_all × 70%

数据源：腾讯实时行情 + 腾讯 K 线全量（每次重新拉取，不做缓存）

usage:
    python cli/sell_alert.py
"""

import io
import os
import sys
from datetime import datetime

# Windows UTF-8 编码
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from core.data_fetcher import fetch_normalized_data, fetch_realtime_quote
from core.position_manager import load_position, POSITION_FILE

# ====== 阈值配置 ======
LOW_BUY_THRESHOLD = 1.15   # 买入均价 ≤ 历史最低 × 1.15 视为低点买入
SELL_LOWER = 0.45          # 目标区间下边界：历史最高 × 45%
SELL_UPPER = 0.70          # 目标区间上边界：历史最高 × 70%

DISCLAIMER = "分析结果仅供参考，不构成任何投资建议。投资有风险，入市需谨慎。"

# 股票名称映射（从 buy_alert.py 复用的已知名称表 + akshare 实时获取）
NAMES: dict[str, str] = {}
try:
    import akshare as ak
    df = ak.stock_info_a_code_name()
    for _, row in df.iterrows():
        NAMES[row["code"]] = row["name"]
except Exception:
    pass

KNOWN: dict[str, str] = {
    "000001": "平安银行", "000002": "万科A", "000568": "泸州老窖",
    "000596": "古井贡酒", "000625": "长安汽车", "000690": "宝新能源",
    "000858": "五粮液", "002304": "洋河股份", "002352": "顺丰控股",
    "002459": "晶澳科技", "002469": "三维化学", "002594": "比亚迪",
    "002855": "捷荣技术", "002920": "德赛西威", "300122": "智飞生物",
    "300498": "温氏股份", "300529": "健帆生物", "300760": "迈瑞医疗",
    "600048": "保利发展", "600085": "同仁堂", "600104": "上汽集团",
    "600370": "*ST三房", "600436": "片仔癀", "600438": "通威股份",
    "600567": "山鹰国际", "600585": "海螺水泥", "600720": "中交设计",
    "600795": "国电电力", "600809": "山西汾酒", "600845": "宝信软件",
    "600887": "伊利股份", "601012": "隆基绿能", "601238": "广汽集团",
    "603395": "红四方", "603833": "欧派家居", "688036": "传音控股",
    "688169": "石头科技", "688223": "晶科能源", "688271": "联影医疗",
    "920802": "保丽洁",
}
for k, v in KNOWN.items():
    if k not in NAMES:
        NAMES[k] = v


def _get_name(code: str) -> str:
    """获取股票名称。"""
    return NAMES.get(code, "???")


def main() -> None:
    """主入口：扫描所有持仓，判断卖出提醒条件，输出表格。"""
    now = datetime.now()
    print(f"=== 卖出提醒扫描 === {now.strftime('%Y-%m-%d %H:%M')}")
    print()
    print("  低点买入持仓 → 接近最高点 45%-70% 出仓区间")
    print()

    # ── 扫描持仓目录 ──
    if not POSITION_FILE.exists():
        print("  无持仓记录。")
        print()
        _print_footer(now, 0, 0, 0)
        return

    position_files = sorted(
        f for f in os.listdir(POSITION_FILE)
        if f.endswith(".json") and f != "portfolio_snapshots"
    )

    if not position_files:
        print("  无持仓记录。")
        print()
        _print_footer(now, 0, 0, 0)
        return

    results: list[dict] = []
    low_buy_count = 0
    skipped: list[dict] = []   # 不符合条件的持仓及原因

    for fname in position_files:
        code = fname.replace(".json", "")
        pos = load_position(code)
        if pos is None or pos.total_shares == 0:
            continue

        avg_cost = pos.avg_cost

        # ── 数据获取：实时行情 + 全量K线（force_refresh，不走缓存） ──
        try:
            quote = fetch_realtime_quote(code)
            cur = float(quote.get("f43", 0)) / 100  # 腾讯格式：价格×100
            if cur <= 0:
                skipped.append({
                    "code": code, "name": _get_name(code),
                    "avg_cost": avg_cost, "reason": "实时行情不可用",
                })
                continue
        except Exception:
            skipped.append({
                "code": code, "name": _get_name(code),
                "avg_cost": avg_cost, "reason": "实时行情获取失败",
            })
            continue

        try:
            data = fetch_normalized_data(stock_code=code, force_refresh=True)
            if not data.prices or len(data.prices) < 50:
                skipped.append({
                    "code": code, "name": _get_name(code),
                    "avg_cost": avg_cost, "reason": f"K线数据不足({len(data.prices)}条)",
                })
                continue
            high_all = max(p.high for p in data.prices)
            low_all = min(p.low for p in data.prices)
        except Exception:
            skipped.append({
                "code": code, "name": _get_name(code),
                "avg_cost": avg_cost, "reason": "K线数据获取失败",
            })
            continue

        # ── 条件 1：低点买入判断 ──
        is_low_buy = avg_cost <= low_all * LOW_BUY_THRESHOLD

        # ── 条件 2：目标区间判断 ──
        target_low = high_all * SELL_LOWER
        target_high = high_all * SELL_UPPER
        in_range = target_low <= cur <= target_high

        if in_range:
            dist = "已触发"
        elif cur < target_low:
            gap_pct = (target_low / cur - 1) * 100
            dist = f"↓{gap_pct:.0f}%"
        else:
            gap_pct = (cur / target_high - 1) * 100
            dist = f"↑{gap_pct:.0f}%"

        pnl_pct = (cur / avg_cost - 1) * 100

        result = {
            "code": code,
            "name": _get_name(code),
            "cur": cur,
            "avg_cost": avg_cost,
            "high_all": high_all,
            "low_all": low_all,
            "target_low": target_low,
            "target_high": target_high,
            "dist": dist,
            "pnl_pct": pnl_pct,
            "in_range": in_range,
            "is_low_buy": is_low_buy,
        }
        if is_low_buy:
            low_buy_count += 1
            results.append(result)
        else:
            from_low_pct = (avg_cost / low_all - 1) * 100
            skipped.append({
                "code": code, "name": _get_name(code),
                "avg_cost": avg_cost, "reason": f"买入价高于历史最低{from_low_pct:.0f}%",
            })

    # ── 排序：已触发排最前，然后按距区间从小到大 ──
    def _sort_key(r: dict) -> tuple:
        if r["in_range"]:
            return (0, 0)
        if r["dist"].startswith("↓"):
            return (0, float(r["dist"].strip("↓%")) + 0.01)
        return (1, float(r["dist"].strip("↑%")))

    results.sort(key=_sort_key)

    # ── 输出表格 ──
    triggered = [r for r in results if r["in_range"]]

    if not results:
        print("  无符合低点买入条件的持仓。")
        print()
        if skipped:
            print("  不符合条件原因：")
            for s in skipped:
                print(f"    {s['code']} {s['name']}: {s['reason']}")
        _print_footer(now, 0, len(position_files), low_buy_count)

    print(f"{'#':>3}  {'代码':<8} {'名称':<8} {'现价':>7} {'均价':>7} "
          f"{'历史最高':>9} {'目标区间':>16} {'距区间':>6} {'盈亏':>6}")
    print("──  " + "─" * 95)

    for i, r in enumerate(results, 1):
        tag = "⚡" if r["in_range"] else "  "
        target_range = f"{r['target_low']:.2f}~{r['target_high']:.2f}"
        print(f"{i:>3}  {r['code']:<8} {r['name']:<8} {r['cur']:>7.2f} {r['avg_cost']:>7.2f} "
              f"{r['high_all']:>9.2f} {target_range:>16} {r['dist']:>6} {r['pnl_pct']:>+5.1f}%")

    print("──  " + "─" * 95)
    print()

    _print_footer(now, len(triggered), len(position_files), low_buy_count)

    # ── 触发告警 ──
    for r in triggered:
        from_low_pct = (r["avg_cost"] / r["low_all"] - 1) * 100
        print(f"  ⚡ {r['code']} {r['name']}：当前 {r['cur']:.2f} "
              f"已进入目标区间 {r['target_low']:.2f}~{r['target_high']:.2f}")
        print(f"     买入均价 {r['avg_cost']:.2f}"
              f"（距历史最低 +{from_low_pct:.1f}%） → 可考虑出仓")
        print()

    if triggered:
        pass
    else:
        print("  本次无触发。")
        print()

    print(f"  {DISCLAIMER}")


def _print_footer(scan_time: datetime, triggered: int, total_positions: int, low_buy: int) -> None:
    """打印底部汇总信息。"""
    print(f"── 触发 {triggered} 只 | 扫描 {total_positions} 只持仓"
          f" | {low_buy} 只符合低点买入条件")
    print(f"── 数据: 腾讯实时行情 + 全量K线 | 刷新时间: {scan_time.strftime('%H:%M:%S')}")
    print()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证脚本能独立运行（手动）**

```bash
cd /c/Users/Administrator/byd-stock-analyzer && .venv/Scripts/python.exe cli/sell_alert.py
```

Expected: 输出表格，列出低点买入持仓和卖出提醒状态（可能全部在区间外，正常）。

- [ ] **Step 3: Commit**

```bash
git add cli/sell_alert.py
git commit -m "feat: add sell_alert.py — 低点买入后高点出仓提醒"
```

---

### Task 2: 添加测试

**Files:**
- Create: `tests/test_sell_alert.py`

- [ ] **Step 1: 写测试文件**

```python
"""sell_alert.py 单元测试 — 条件判断逻辑。"""

import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 确保 sell_alert 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---- 模拟 Position 数据 ----

@pytest.fixture
def mock_position_low_buy():
    """低点买入持仓：均价 78.50，历史最低 78.00（78.50 ≤ 78 × 1.15 = 89.70 ✅）"""
    return {
        "stock_code": "002594",
        "trigger_base": None,
        "entries": [
            {"date": "2026-07-01", "price": 78.50, "shares": 100, "entry_type": "initial"}
        ],
    }


@pytest.fixture
def mock_position_high_buy():
    """高点买入持仓：均价 150.00，历史最低 78.00（150 > 78 × 1.15 = 89.70 ❌）"""
    return {
        "stock_code": "002594",
        "trigger_base": None,
        "entries": [
            {"date": "2026-01-01", "price": 150.00, "shares": 100, "entry_type": "initial"}
        ],
    }


# ---- 测试：低点买入判断逻辑 ----

def test_low_buy_detection():
    """均价 78.50，历史最低 78.00 → 78.50 ≤ 89.70 → 低点买入 ✅"""
    from cli.sell_alert import LOW_BUY_THRESHOLD

    avg_cost = 78.50
    low_all = 78.00
    assert avg_cost <= low_all * LOW_BUY_THRESHOLD


def test_not_low_buy():
    """均价 150，历史最低 78 → 150 > 89.70 → 非低点买入 ❌"""
    from cli.sell_alert import LOW_BUY_THRESHOLD

    avg_cost = 150.00
    low_all = 78.00
    assert avg_cost > low_all * LOW_BUY_THRESHOLD


# ---- 测试：目标区间判断 ----

def test_in_target_range():
    """当前价 90，历史最高 200 → 目标区间 90~140 → 90 在区间内 ✅"""
    from cli.sell_alert import SELL_LOWER, SELL_UPPER

    cur = 90.0
    high_all = 200.0
    target_low = high_all * SELL_LOWER   # 90
    target_high = high_all * SELL_UPPER  # 140
    assert target_low <= cur <= target_high


def test_below_target_range():
    """当前价 80，历史最高 200 → 目标区间 90~140 → 80 在区间下 ❌"""
    from cli.sell_alert import SELL_LOWER, SELL_UPPER

    cur = 80.0
    high_all = 200.0
    target_low = high_all * SELL_LOWER
    target_high = high_all * SELL_UPPER
    assert cur < target_low


def test_above_target_range():
    """当前价 150，历史最高 200 → 目标区间 90~140 → 150 在区间上 ❌"""
    from cli.sell_alert import SELL_LOWER, SELL_UPPER

    cur = 150.0
    high_all = 200.0
    target_low = high_all * SELL_LOWER
    target_high = high_all * SELL_UPPER
    assert cur > target_high


def test_edge_case_exact_boundary():
    """边界值测试：当前价正好等于下边界"""
    from cli.sell_alert import SELL_LOWER, SELL_UPPER

    high_all = 100.0
    cur = high_all * SELL_LOWER   # 45.0
    assert high_all * SELL_LOWER <= cur <= high_all * SELL_UPPER


# ---- 测试：盈亏计算 ----

def test_pnl_positive():
    """均价 78.50，现价 90 → 盈亏 +14.6%"""
    avg_cost = 78.50
    cur = 90.0
    pnl = (cur / avg_cost - 1) * 100
    assert pnl > 0
    assert round(pnl, 1) == 14.6


def test_pnl_negative():
    """均价 10.38，现价 9.50 → 盈亏 -8.5%"""
    avg_cost = 10.38
    cur = 9.50
    pnl = (cur / avg_cost - 1) * 100
    assert pnl < 0
    assert round(pnl, 1) == -8.5


# ---- 测试：距离标签 ----

def test_dist_label_already_in_range():
    """已触发的显示'已触发'"""
    cur = 100.0
    high_all = 200.0
    target_low = high_all * 0.45   # 90
    target_high = high_all * 0.70  # 140
    in_range = target_low <= cur <= target_high
    assert in_range

    if in_range:
        dist = "已触发"
    assert dist == "已触发"


def test_dist_label_below():
    """低于区间下边界 → 显示 ↓百分比（离下边界还差多少）"""
    cur = 80.0
    high_all = 200.0
    target_low = high_all * 0.45  # 90
    gap_pct = (target_low / cur - 1) * 100
    dist = f"↓{gap_pct:.0f}%"
    assert dist == "↓12%"


def test_dist_label_above():
    """高于区间上边界 → 显示 ↑百分比（已超出上边界多少）"""
    cur = 160.0
    high_all = 200.0
    target_high = high_all * 0.70  # 140
    gap_pct = (cur / target_high - 1) * 100
    dist = f"↑{gap_pct:.0f}%"
    assert dist == "↑14%"
```

- [ ] **Step 2: 运行测试验证通过**

```bash
cd /c/Users/Administrator/byd-stock-analyzer && .venv/Scripts/python.exe -m pytest tests/test_sell_alert.py -v
```

Expected: 9 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_sell_alert.py
git commit -m "test: add sell_alert unit tests — 9 tests covering conditions and edge cases"
```

---

### Task 3: 添加 Cron 定时任务

**Files:**
- No file changes — use CronCreate tool

- [ ] **Step 1: 创建持久化 Cron 任务**

使用 CronCreate 工具，参数：
```json
{
  "cron": "30 9 * * 1-5,0 11 * * 1-5,0 14 * * 1-5,50 14 * * 1-5",
  "prompt": "卖出提醒扫描: cd /c/Users/Administrator/byd-stock-analyzer && .venv/Scripts/python.exe cli/sell_alert.py",
  "recurring": true,
  "durable": true
}
```

> **注意：** 如果 CronCreate 不支持多时间点合并到一个 cron 表达式，则创建 4 个独立的持久化任务：
> - 09:30 — `30 9 * * 1-5`
> - 11:00 — `0 11 * * 1-5`
> - 14:00 — `0 14 * * 1-5`
> - 14:50 — `50 14 * * 1-5`

- [ ] **Step 2: 验证 Cron 已创建**

```bash
# 使用 CronList 工具确认 13 个持久化任务全部在线
```

- [ ] **Step 3: 手动触发一次验证**

```bash
cd /c/Users/Administrator/byd-stock-analyzer && .venv/Scripts/python.exe cli/sell_alert.py
```

Expected: 输出完整的持仓扫描表格。

---

### Task 4: 端到端验证

- [ ] **Step 1: 全量测试通过**

```bash
cd /c/Users/Administrator/byd-stock-analyzer && .venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: 28 + 9 = 37 passed（sell_alert 9 个 + 现有 28 个）。

- [ ] **Step 2: 执行 sell_alert 确认输出格式正确**

```bash
cd /c/Users/Administrator/byd-stock-analyzer && .venv/Scripts/python.exe cli/sell_alert.py
```

Expected: 表格包含所有 7 只持仓，低点买入的标出，已进入目标区间的 ⚡ 标记。

- [ ] **Step 3: 更新 CLAUDE.md 并打 tag**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md — sell_alert feature + 13 cron tasks"
git tag stable-2026-07-06
```

- [ ] **Step 4: 推送**

```bash
git push origin main --tags
```

---

## Summary

| Task | 内容 | 文件 |
|:--:|------|------|
| 1 | 创建 `sell_alert.py` | `cli/sell_alert.py`（新建） |
| 2 | 添加测试 | `tests/test_sell_alert.py`（新建） |
| 3 | 添加 Cron | `scheduled_tasks.json`（+4 条） |
| 4 | 端到端验证 | 测试 + 手动运行 + commit + push |
