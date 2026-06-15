# Phase 9: 方向预测 + 回测 ✅ DONE

**Status:** Complete | **Commits:** 5bf9455, 90222ca, 872a285

## Deliverables

| File | Purpose |
|------|---------|
| `core/backtester.py` | 6指标投票方向预测 + 300天历史回测 |
| `cli/main.py:predict` | 方向预测面板 + 二维决策矩阵 |

## 6-Indicator Voting

| # | Indicator | Bull Signal | Bear Signal |
|---|-----------|-------------|-------------|
| 1 | MACD | Hist > 0.3 | Hist < -0.3 |
| 2 | RSI | <30 (1票) / <40 (0.5票) | >70 / >60 |
| 3 | MA | 金叉 (1票) / 多头 (0.3票) | 死叉 / 空头 |
| 4 | Bollinger | pos<0.1 (1票) / <0.25 (0.5票) | >0.9 / >0.75 |
| 5 | Volume | 放量上涨 (1票) | 放量下跌 |
| 6 | Momentum | >0.3% (0.7票) | <-0.3% |

## Backtest Results
- 300天回测: 纯方向准确率 ~48%, 无信号率 20%
- 诚实结论: 短期方向接近随机，48%为市场有效假说天花板

## 2D Decision Matrix
```
评分 × 方向 → 6种操作: 强烈买入/等待低吸/轻仓试探/建议卖出/观望等待/强烈卖出
```
