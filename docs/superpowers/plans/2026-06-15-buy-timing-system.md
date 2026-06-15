# 买入时机预测系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为所有关注股票提供精确的买入时机判断——"距买入还差什么条件、需要股价到什么位置、加仓是否触发"。

**Architecture:** 在现有评分+持仓系统上增加买入条件反向计算 + 统一仪表盘。核心逻辑是"目标导向"——不是问"现在评分多少"，而是问"要触发买入，还需要什么变化"。

**Tech Stack:** Python + 现有 core/ 模块 + Rich CLI

---

### Task 1: 买入条件反向计算器

**Files:**
- Create: `core/buy_timing.py`
- Modify: 无

**Goal:** 给定当前评分，反向计算需要什么条件变化才能达到目标分（70分）。

- [ ] **Step 1: 创建 buy_timing.py —— 反向评分计算**

```python
"""买入时机精确计算——从当前评分反推需要什么条件才能触发买入。"""

from core.config import DEFAULT_WEIGHTS


def calculate_path_to_buy(
    current_score: int,
    pe_percentile: float | None,
    pb_percentile: float | None,
    trend: str,
    current_price: float,
    ma20: float | None,
    ma50: float | None,
) -> dict:
    """计算到达买入评分(70分)需要的条件变化。

    Returns:
        need_pts: 还差多少分
        paths: 可选的达标路径列表
    """
    need_pts = max(0, 70 - current_score)

    paths = []

    # 路径1: PE 回落
    if pe_percentile and pe_percentile > 40:
        # PE 分位每降 10%, 估值因子提升 10*0.35=3.5 分
        pe_drop_needed = need_pts / (0.35 * 10) * 10  # 需要 PE 分位降多少
        target_pe_pct = max(10, pe_percentile - pe_drop_needed)
        # 假设 PE 不变, 股价需要跌多少
        if current_price > 0:
            price_ratio = target_pe_pct / pe_percentile
            target_price = round(current_price * price_ratio, 2)
        else:
            target_price = 0
        paths.append({
            "type": "PE 回落",
            "description": f"市盈率分位从 {pe_percentile:.0f}% 降至 {target_pe_pct:.0f}%",
            "price_target": target_price,
            "effort": "被动等待" if trend == "down" else "需要股价下跌推动",
        })

    # 路径2: 趋势反转
    if trend in ("down", "sideways_down"):
        # 趋势从 down→up 提升 70 分 (20% 权重 → 14 分)
        paths.append({
            "type": "趋势反转",
            "description": f"MA20 从 {ma20 or '?'} 站上 MA50 {ma50 or '?'}",
            "price_target": ma50 if ma50 else None,
            "effort": "等待均线金叉",
        })

    # 路径3: 综合改善（PE回落 + 趋势改善）
    if pe_percentile and pe_percentile > 50 and trend in ("down", "sideways_down"):
        pe_target = max(30, pe_percentile - 15)
        paths.append({
            "type": "综合改善",
            "description": f"PE 降至 {pe_target:.0f}% + 趋势翻转为 up",
            "price_target": round(current_price * (pe_target / pe_percentile), 2) if pe_percentile > 0 else None,
            "effort": "最可能路径",
        })

    return {
        "need_pts": need_pts,
        "current_score": current_score,
        "target_score": 70,
        "paths": paths,
        "at_buy": current_score >= 70,
    }
```

- [ ] **Step 2: 测试反向计算**

```bash
cd ~/byd-stock-analyzer && python -c "
from core.buy_timing import calculate_path_to_buy
# 模拟比亚迪: 51分, PE 83%, trend down
result = calculate_path_to_buy(51, 83.0, 2.0, 'down', 90.94, 93.87, 98.37)
print(f'差 {result[\"need_pts\"]} 分')
for p in result['paths']:
    print(f'  {p[\"type\"]}: {p[\"description\"]} → 目标价 {p.get(\"price_target\",\"?\")}')
"
```

Expected output should show 2-3 actionable paths.

- [ ] **Step 3: Commit**

```bash
git add core/buy_timing.py
git commit -m "feat: buy timing reverse calculator — what conditions needed to reach buy score"
```

---

### Task 2: 统一仪表盘命令

**Files:**
- Modify: `cli/main.py` — add `dashboard` command

**Goal:** 一个命令展示所有关注股票的买入时机、持仓盈亏、加仓信号。

- [ ] **Step 1: 在 main.py 添加 dashboard 命令**

在 `scan` 命令后面插入:

```python
@app.command()
def dashboard() -> None:
    """统一仪表盘——买入时机 + 持仓盈亏 + 加仓信号。"""
    import io as _io
    from core.position_manager import load_position, should_add
    from core.buy_timing import calculate_path_to_buy

    stocks = ["002594", "920839", "600370", "600567"]

    console.print()
    console.print("[bold]买入时机仪表盘[/bold]")
    console.print(f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M')}[/dim]")
    console.print()

    # 大盘
    from core.market_context import get_market_regime
    market = get_market_regime()
    regime_labels = {"bull": "牛市", "bear": "熊市", "sideways": "震荡"}
    console.print(f"大盘: {regime_labels.get(market.get('regime','?'),'?')} | "
                  f"上证50 {market.get('index_level',0):.2f}")
    console.print()

    table = Table(title="买入时机")
    table.add_column("代码")
    table.add_column("现价", justify="right")
    table.add_column("评分", justify="right")
    table.add_column("距买入", justify="center")
    table.add_column("最快路径", justify="left")
    table.add_column("持仓", justify="right")

    for code in stocks:
        _saved = sys.stdout
        sys.stdout = _io.StringIO()
        try:
            from core.data_fetcher import fetch_normalized_data, fetch_valuation_data
            data = fetch_normalized_data(stock_code=code, force_refresh=False)
            from core.analyzers.technical import analyze as at
            result = at(data)
            try:
                valuation = fetch_valuation_data(stock_code=code)
            except Exception:
                valuation = None
            from core.analyzers.valuation import analyze as av
            result = av(result, valuation)
            from core.scoring import compute as cs
            sr = cs(result)

            timing = calculate_path_to_buy(
                sr.score, result.pe_percentile, result.pb_percentile,
                result.trend, data.latest_price, result.ma_20, result.ma_50
            )
        finally:
            sys.stdout = _saved

        pos = load_position(code)
        pos_str = ""
        if pos:
            pnl = pos.unrealized_pnl(data.latest_price)
            pos_str = f"{pos.total_shares}股 | {pnl['pnl_pct']:+.1f}%"
            if pos.can_add and data.latest_price <= pos.next_add_price:
                pos_str += " [加仓]"

        best_path = timing["paths"][0]["description"][:30] + "..." if timing["paths"] else "条件复杂"
        need_str = f"[green]可买入[/green]" if timing["at_buy"] else f"[yellow]-{timing['need_pts']}分[/yellow]"
        score_color = "green" if sr.score >= 70 else ("yellow" if sr.score >= 56 else "red")

        table.add_row(
            code,
            f"{data.latest_price:.2f}",
            f"[{score_color}]{sr.score}[/{score_color}]",
            need_str,
            best_path,
            pos_str or "无持仓",
        )

    console.print(table)
    console.print()
    console.print(DISCLAIMER)
```

- [ ] **Step 2: 测试 dashboard**

```bash
python -m cli.main dashboard
```

Expected: 4只股票一览表，比亚迪显示"还差19分"，920839显示"还差6分"，600370显示持仓+加仓触发。

- [ ] **Step 3: 注册 dashboard 到路由**

在 `if __name__ == "__main__"` 中添加 `"dashboard"` 到命令白名单。

- [ ] **Step 4: Commit**

```bash
git add cli/main.py
git commit -m "feat: unified dashboard — buy timing + positions + add signals in one view"
```

---

### Task 3: Cron 仪表盘推送

**Files:**
- Modify: 更新 Cron 任务 prompt

**Goal:** 交易时段 Cron 任务改为运行 dashboard 而非单独的 predict，一次看到全貌。

- [ ] **Step 1: 删除旧 Cron，创建新 dashboard Cron**

```bash
# 取消旧的 4 个定时 predict
CronDelete bfc4f083
CronDelete 2da6aae7
CronDelete f553c20f
CronDelete c50ebabc
```

- [ ] **Step 2: 创建 dashboard Cron**

```bash
CronCreate "3 10 * * 1-5" "cd ~/byd-stock-analyzer && python -m cli.main dashboard"
CronCreate "57 10 * * 1-5" "cd ~/byd-stock-analyzer && python -m cli.main dashboard"
CronCreate "57 13 * * 1-5" "cd ~/byd-stock-analyzer && python -m cli.main dashboard"
CronCreate "57 14 * * 1-5" "cd ~/byd-stock-analyzer && python -m cli.main dashboard"
```

按用户确认后执行。

- [ ] **Step 3: 验证 Cron 列表**

```bash
CronList
```

---

### Task 4: 端到端验证

- [ ] **Step 1: 全命令回归**

```bash
python -m cli.main predict           # 预测+建议
python -m cli.main dashboard          # 统一仪表盘
python -m cli.main scan               # 多股票扫描
python -m cli.main position           # 持仓管理
python -m cli.main position -s 600370 # 600370 持仓
python -m cli.main backtest --days 50 # 回测
```

- [ ] **Step 2: 买入时机逻辑验证**

```python
from core.buy_timing import calculate_path_to_buy
# 920839 应该只剩趋势确认就够
r = calculate_path_to_buy(64, 12.0, 7.0, "unknown", 29.35, None, None)
assert r["need_pts"] == 6
assert not r["at_buy"]
print("PASS")
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test: e2e validation for buy timing system"
```

---

### 成功标准

| 指标 | 目标 |
|------|:--:|
| dashboard 展示 | 4只股票 + 买入差距 + 持仓盈亏 + 加仓信号 |
| 买入路径计算 | 给出至少1条具体路径（如"PE降至X%触发"） |
| Cron 运行 | 交易时段4次 dashboard 推送 |
| 向后兼容 | predict/scan/position/backtest 不受影响 |
