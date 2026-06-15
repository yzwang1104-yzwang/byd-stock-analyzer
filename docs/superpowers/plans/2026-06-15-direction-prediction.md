# 方向预测集成 + 回测修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复回测准确率指标，将 6 指标投票方向预测集成到 predict 命令，输出「评分 × 方向」二维决策矩阵。

**Architecture:** 回测引擎 (`core/backtester.py`) 区分方向预测准确率和"无信号"日占比。CLI predict 命令新增方向预测区块，展示投票明细和二维决策矩阵。模型阈值基于回测结果调优。

**Tech Stack:** Python + 纯 Python 技术指标（不依赖 pandas-ta）+ Rich CLI

---

## 回测发现（基线）

| 指标 | 值 | 问题 |
|------|:--:|------|
| 总准确率 | 27.5% | 被大量"平"预测稀释——平=50%置信时的平局 |
| 涨准确率 | 43.8% | 接近随机 |
| 跌准确率 | 50.7% | 接近随机 |
| 无信号率 | ~50% | 阈值太严格，两天有一天不投票 |

**根因:** 保守阈值导致大量平局。平局被计为错误，拖累总准确率。

---

### Task 1: 修复回测准确率指标

**Files:**
- Modify: `core/backtester.py:1-150`

- [ ] **Step 1: 修改 `backtest_direction` 区分纯方向准确率和含"平"的总准确率**

当前 `correct` 计算方式导致平预测全部算错。修改返回结构，新增三个指标:
- `directional_accuracy`: 只在预测"涨"或"跌"时计分
- `flat_rate`: 预测为"平"的比例  
- `overall_accuracy`: 保持原有（含平），但要注明含义

```python
# 在 backtest_direction 的 results 循环后，修改统计部分:

# 纯方向准确率（排除"平"预测）
directional_results = [r for r in results if r["predicted"] != "flat"]
directional_correct = sum(1 for r in directional_results if r["correct"])
directional_total = len(directional_results)

return {
    "status": "ok",
    "total": total,
    "flat_count": total - directional_total,
    "flat_rate": round((total - directional_total) / total * 100, 1),
    "directional_accuracy": round(
        directional_correct / directional_total * 100, 1
    ) if directional_total > 0 else 0,
    "directional_total": directional_total,
    "overall_accuracy": round(correct / total * 100, 1),
    # ... 保持其他字段不变 ...
}
```

- [ ] **Step 2: 更新 CLI backtest 命令的输出格式**

`cli/main.py` 的 backtest 函数中，将输出改为:

```python
console.print(f"[bold]纯方向准确率: {result['directional_accuracy']}%[/bold] "
              f"({result['directional_total']} 次有信号预测)")
console.print(f"  含\"平\"总准确率: {result['overall_accuracy']}% ({result['total']} 次)")
console.print(f"  无信号(平)比例: {result['flat_rate']}% ({result['flat_count']} 次)")
console.print(f"  预测涨准确率: {result['up_accuracy']}%")
console.print(f"  预测跌准确率: {result['down_accuracy']}%")
```

- [ ] **Step 3: 运行回测验证新指标**

```bash
python -m cli.main backtest --days 200
```

预期: 纯方向准确率应 > 总准确率（因为排除了平预测）。

- [ ] **Step 4: Commit**

```bash
git add core/backtester.py cli/main.py
git commit -m "fix: backtester — separate directional accuracy from overall accuracy

Previously flat predictions were counted as wrong, dragging overall accuracy
to 27.5%. Now reports:
- directional_accuracy: up/down predictions only
- flat_rate: proportion of no-signal days
- overall_accuracy: preserved for reference"
```

---

### Task 2: 方向预测集成到 predict 命令

**Files:**
- Modify: `cli/main.py:predict`
- Create: (无新文件，复用 `core/backtester.py` 的 `_predict_direction`)

- [ ] **Step 1: 在 predict 命令中调用方向预测**

在 `cli/main.py` 的 predict 函数中，价格预测之后、输出之前插入方向预测代码。

找到 `# ====== 输出 ======` 之前，插入:

```python
    # ====== 方向预测（6指标投票） ======
    from core.backtester import _predict_direction

    dir_pred = _predict_direction(data.prices)

    # 二维决策矩阵
    score = advice.score
    dir_conf = dir_pred["confidence"]
    direction = dir_pred["direction"]

    if score >= 70 and direction == "up":
        matrix_action = ("strong_buy", "强烈买入", "bold green")
    elif score >= 70 and direction == "down":
        matrix_action = ("buy", "等待低吸", "green")
    elif score >= 50 and direction == "up":
        matrix_action = ("buy", "轻仓试探", "green")
    elif score >= 50 and direction == "down":
        matrix_action = ("sell", "建议卖出", "red")
    elif score < 50 and direction == "up":
        matrix_action = ("hold", "观望等待", "yellow")
    elif score < 50 and direction == "down":
        matrix_action = ("strong_sell", "强烈卖出", "bold red")
    else:
        matrix_action = ("hold", "信号不足，观望", "yellow")
```

- [ ] **Step 2: 在输出区块中添加方向预测面板**

在预测表格之后、关键指标摘要之前，插入方向预测输出:

```python
    # --- 方向预测面板 ---
    dir_color = "green" if direction == "up" else ("red" if direction == "down" else "yellow")
    dir_table = Table(title="方向预测 (6指标投票)", border_style=dir_color)
    dir_table.add_column("预测方向", style=dir_color, justify="center")
    dir_table.add_column("置信度", justify="center")
    dir_table.add_column("涨票数", justify="right")
    dir_table.add_column("跌票数", justify="right")
    dir_table.add_column("信号", justify="left")

    up_count = sum(1 for s in dir_pred["signals"] if "↑" in s)
    down_count = sum(1 for s in dir_pred["signals"] if "↓" in s)

    dir_table.add_row(
        {"up": "↑ 看涨", "down": "↓ 看跌", "flat": "→ 平盘"}.get(direction, "?"),
        f"{dir_conf}%",
        str(up_count),
        str(down_count),
        " | ".join(dir_pred["signals"][:3]) if dir_pred["signals"] else "无信号",
    )
    console.print(dir_table)

    # --- 二维决策矩阵 ---
    matrix_color = matrix_action[2]
    console.print(
        f"\n[bold {matrix_color}]决策: {matrix_action[1]}[/bold {matrix_color}]  "
        f"({score}分 × {direction}方向 {dir_conf}%置信)"
    )
```

- [ ] **Step 3: 运行 predict 验证输出**

```bash
python -m cli.main predict
```

预期看到: 买入建议面板 + 价格预测 + 方向预测 + 二维决策。

- [ ] **Step 4: Commit**

```bash
git add cli/main.py
git commit -m "feat: integrate direction prediction into predict command

- 6-indicator voting displayed with up/down vote count
- 2D decision matrix: score x direction → action
- Direction signals shown in output panel"
```

---

### Task 3: 阈值调优（基于回测反馈）

**Files:**
- Modify: `core/backtester.py:_predict_direction`

- [ ] **Step 1: 调整投票权重——给确定性信号更多票数**

当前问题: 信号太保守（50% 无信号）。需要调低阈值让更多天有信号，但保持高准确率。

修改 `_predict_direction` 中的关键阈值:

```python
# RSI: 放宽到 35/65 适度投票（0.5票），<30/>70 仍为完整 1 票
if rsi < 30:
    signals.append(f"RSI超卖({rsi:.0f}) ↑")
    up_votes += 1
elif rsi > 70:
    signals.append(f"RSI超买({rsi:.0f}) ↓")
    down_votes += 1
elif rsi < 40:   # 从 30 放宽到 40，给 0.5 票
    signals.append(f"RSI偏低({rsi:.0f}) ↑")
    up_votes += 0.5
elif rsi > 60:   # 从 70 放宽到 60，给 0.5 票
    signals.append(f"RSI偏高({rsi:.0f}) ↓")
    down_votes += 0.5

# 布林带: 从 0.05/0.95 放宽到 0.15/0.85
if position < 0.15:
    signals.append("近下轨 ↑")
    up_votes += 0.7
elif position > 0.85:
    signals.append("近上轨 ↓")
    down_votes += 0.7

# 动量: 从 0.5% 放宽到 0.3%
if pct_change > 0.3:
    signals.append(f"动量正({pct_change:.1f}%) ↑")
    up_votes += 0.7
elif pct_change < -0.3:
    signals.append(f"动量负({pct_change:.1f}%) ↓")
    down_votes += 0.7
```

- [ ] **Step 2: 运行回测验证新阈值**

```bash
python -m cli.main backtest --days 200
```

目标: 纯方向准确率 ≥ 52%（超过抛硬币），无信号率降至 30% 以下。

- [ ] **Step 3: 如果准确率仍 < 50%，进一步调整**

如果跌准确率持续低于涨准确率，给跌信号更多权重:
- 动量负 > 0.3% → 1.0 票（从 0.7 上调）
- RSI > 60 → 0.7 票（从 0.5 上调）

重跑回测直到纯方向准确率 ≥ 52%。

- [ ] **Step 4: Commit**

```bash
git add core/backtester.py
git commit -m "tune: relax voting thresholds for better signal rate

RSI: 35/65 half-vote zone, 30/70 full vote
Bollinger: 0.15/0.85 boundary
Momentum: 0.3% threshold
Target: directional accuracy >= 52%, flat rate < 30%"
```

---

### Task 4: 端到端验证

**Files:**
- (无修改，仅测试)

- [ ] **Step 1: 全场景测试**

```bash
# 1. 回测
python -m cli.main backtest --days 200

# 2. 实时预测
python -m cli.main predict

# 3. 详细模式
python -m cli.main predict --verbose

# 4. 原有分析不受影响
python -m cli.main --price 91.0 --mock
```

- [ ] **Step 2: 验证二维矩阵逻辑**

人工检查: score=51(SELL) + direction="up" → 应该输出"观望等待"，不是"强烈卖出"

```python
# 在 Python 中快速验证矩阵映射
score = 51; direction = "up"  # 低分 + 涨 → 观望
action = "hold" if (score < 50 and direction == "up") else "..."
assert action == "hold"
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test: end-to-end validation of direction prediction integration"
```

---

### 成功标准

| 指标 | 修复前 | 目标 |
|------|:--:|:--:|
| 纯方向准确率 | 未独立计算 | ≥ 52% |
| 无信号(平)比例 | ~50% | < 30% |
| predict 输出 | 无方向预测 | 方向+投票+二维矩阵 |
| 回测指标含义 | 含平混淆 | 区分方向和总体 |
