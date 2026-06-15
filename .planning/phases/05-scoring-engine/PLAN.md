# Phase 5: 评分引擎 ✅ DONE

**Status:** Complete | **Commit:** cc7ea9f

## Deliverables

| File | Purpose |
|------|---------|
| `core/scoring.py` | compute(AnalysisResult, ScoringConfig) → ScoreResult |

## Factor Weights

| Factor | Weight | Scoring Logic |
|--------|--------|---------------|
| Valuation | 35% | 100 - PE_percentile (lower = better) |
| Technical | 30% | RSI + MACD + Bollinger position |
| Trend | 20% | MA structure → up=85, sideways=50, down=15 |
| Volume | 10% | Surge +15, drought -15 |
| Sentiment | 5% | Buy/sell signal count ratio |

## Bearish Protection
- Trend "down" → max 15/100 on trend factor
- RSI overbought → -25 on technical factor
- MACD negative histogram → -10 on technical factor
