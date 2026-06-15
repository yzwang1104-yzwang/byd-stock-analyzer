# Phase 6: 决策逻辑与信号 ✅ DONE

**Status:** Complete | **Commit:** cc7ea9f

## Deliverables

| File | Purpose |
|------|---------|
| `core/advice.py` | generate(ScoreResult, AnalysisResult) → AdviceResult |

## Score → Action Mapping

| Score | Action | Position |
|-------|--------|----------|
| 0-30 | 强烈卖出 | 0% |
| 31-55 | 建议卖出 | 0-25% |
| 56-75 | 观望等待 | 25-50% |
| 76-90 | 建议买入 | 50-75% |
| 91-100 | 强烈买入 | 75-100% |

## Position Adjustment
Base position from score band → ATR volatility discount:
- ATR/Price > 4% → -25% position
- ATR/Price > 3% → -10% position

## Sell Trigger (SELL-01)
RSI >= 70 AND PE_percentile >= 80% → override to "sell"
