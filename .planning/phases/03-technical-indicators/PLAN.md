# Phase 3: 技术指标计算 ✅ DONE

**Status:** Complete | **Commit:** 4609807

## Deliverables

| File | Purpose |
|------|---------|
| `core/analyzers/technical.py` | analyze(NormalizedData) → AnalysisResult |

## Indicators

| # | Indicator | Params | Signal Detection |
|---|-----------|--------|------------------|
| 1 | SMA | 20, 50, 200 | MA structure → trend |
| 2 | MACD | 12/26/9 | Golden/death cross |
| 3 | RSI | 14 | Oversold <30, Overbought >70 |
| 4 | Bollinger | 20, 2σ | Price at band edges |
| 5 | ATR | 14 | Volatility measurement |
| 6 | Volume SMA | 20 | Surge (>1.5x) / Drought (<0.5x) |

## Critical: shift(1) Look-Ahead Prevention
All indicators computed on `df.shift(1)` — T-day signal uses only data through T-1.
