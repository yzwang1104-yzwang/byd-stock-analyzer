# Phase 8: 价格预测系统 ✅ DONE

**Status:** Complete | **Commits:** 284910b, cbb6346, f0ade97

## Deliverables

| File | Purpose |
|------|---------|
| `core/prediction_tracker.py` | 预测记录、回填、校准（偏差修正+区间乘数） |
| `cli/main.py:predict` | 买入建议+价格预测+方向预测合三为一 |

## Architecture

```
fetch_normalized_data → technical analysis → valuation → scoring → advice
                                                         ↓
                                               price prediction (ATR + momentum + MA/RSI bias)
                                                         ↓
                                              record_prediction → auto_backfill → get_calibration
```

## Key Decisions
- ATR-based range (not stdev*0.4) for realistic volatility
- 3-day weighted momentum (50/30/20)
- MA mean-reversion bias + RSI extreme correction
- Auto-backfill >30min old predictions
