---
phase: code-review
reviewed: 2026-06-17T08:00:00Z
depth: deep
files_reviewed: 8
files_reviewed_list:
  - core/scoring.py
  - core/advice.py
  - core/analyzers/technical.py
  - core/analyzers/valuation.py
  - core/market_context.py
  - core/prediction_tracker.py
  - cli/main.py
  - cli/improvement_loop.py
findings:
  critical: 3
  warning: 7
  info: 7
  total: 17
status: issues_found
---

# Code Review Report

**Reviewed:** 2026-06-17T08:00:00Z
**Depth:** deep (cross-file analysis)
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Reviewed the BYD stock analyzer core engine across 8 files covering the scoring pipeline, technical indicators, valuation analysis, market context, prediction tracking, CLI entry point, and the 11-step improvement loop. The overall architecture is clean with good separation of concerns. Three critical issues were found: a hardcoded stock code in the improvement loop that breaks multi-stock operations, a zero-width prediction interval edge case when ATR data is unavailable, and a hardcoded stock display name when the CLI is used with non-default stocks. Seven warnings cover inconsistent prediction logic between main.py and improvement_loop.py, bare exception handling, missing None guards, and code quality concerns.

---

## Critical Issues

### CR-01: Hardcoded stock code in improvement loop backfill

**File:** `cli/improvement_loop.py:29-30`
**Issue:** `RECORDS_FILE` is hardcoded to `predictions_002594.json` at module level, but `step2_backfill()` accepts a `stock` parameter. When called with a stock other than 002594, backfill data is written to the wrong file (002594's file), causing data corruption for both stocks.

```python
# Line 29-30: HARDCODED to 002594
HISTORY_DIR = Path(".prediction_history")
RECORDS_FILE = HISTORY_DIR / "predictions_002594.json"

# Line 142: accepts stock parameter but ignores it
def step2_backfill(stock: str, current_price: float) -> int:
    # Uses RECORDS_FILE which always points to 002594
    if not RECORDS_FILE.exists():
        return 0
```

**Fix:** Derive `RECORDS_FILE` dynamically from the `stock` parameter instead of using a module-level constant.

```python
def step2_backfill(stock: str, current_price: float) -> int:
    records_file = HISTORY_DIR / f"predictions_{stock}.json"
    if not records_file.exists():
        return 0
    records = json.loads(records_file.read_text())
    # ... rest of function
```

---

### CR-02: Zero-width prediction interval when ATR is unavailable

**File:** `cli/improvement_loop.py:107`
**Issue:** When `result.atr_14` is `None` (which happens when fewer than 14 data points are available), the expression `(result.atr_14 or 0) * 0.6` evaluates to 0, producing a prediction interval of zero width. This means `pred_low == pred_close == pred_high`, making the prediction nonsensical.

```python
atr_range = (result.atr_14 or 0) * 0.6 * market_range_multiplier(market)
pred_low = pred_close - atr_range
pred_high = pred_close + atr_range
```

**Fix:** Fall back to a sensible default like 2% of current price when ATR is unavailable.

```python
if result.atr_14 is not None and result.atr_14 > 0:
    atr_range = result.atr_14 * 0.6 * market_range_multiplier(market)
else:
    atr_range = pred_close * 0.02  # fallback: 2% of current price
```

The same pattern exists in `cli/main.py:350` but is less critical there because `stdev` provides a secondary fallback:
```python
base_atr_range = result.atr_14 * 0.8 if result.atr_14 else stdev * 0.5
```

---

### CR-03: Hardcoded stock display name in analyze command

**File:** `cli/main.py:158`
**Issue:** The `analyze` command accepts a `--stock` parameter (line 82) that controls data fetching, but `generate_advice()` always receives `stock_name="比亚迪"` regardless. When analyzing a different stock (e.g., `--stock 600567`), the output displays "比亚迪" as the stock name, misleading the user.

```python
advice = generate_advice(score_result, result, stock_name="比亚迪", current_price=price)
```

**Fix:** Pass the actual stock name based on the stock code, or use the name from the fetched data.

```python
stock_name = data.stock_name if hasattr(data, 'stock_name') and data.stock_name else stock
advice = generate_advice(score_result, result, stock_name=stock_name, current_price=price)
```

Or at minimum, derive it from the shared stock name in config:
```python
from core.config import STOCK_NAME
# ... but this also only works for 002594
```

The proper fix requires determining the stock name from the data fetcher, which already sets `NormalizedData.stock_name`.

---

## Warnings

### WR-01: Divergent prediction logic between main.py and improvement_loop.py

**File:** `cli/improvement_loop.py:83-102` vs `cli/main.py:338-370`
**Issue:** The prediction calculation logic (momentum, MA bias, RSI bias) is duplicated between `cli/main.py` (the `predict` command) and `cli/improvement_loop.py` (the `step1_fetch` function), but the two implementations produce different results.

In `main.py`:
- MA bias scales proportionally: `gap_pct * cur_price * 0.3`, clamped to +/-0.5
- RSI bias has 4 tiers: <=25:+0.5, <=35:+0.2, >=65:-0.2, >=75:-0.5

In `improvement_loop.py`:
- MA bias is binary: `+0.1` if price < MA50, `-0.1` if price > MA20
- RSI bias has only 2 tiers: <30:+0.3, >70:-0.3

This means the two commands produce different predictions, undermining the trustworthiness of the 11-step loop's results.

**Fix:** Extract the prediction calculation into a shared function in `core/` that both files call, eliminating duplication entirely.

---

### WR-02: Bare exception handling with no logging

**Files:** `cli/improvement_loop.py:61`, `cli/main.py:120,141,295,307`
**Issue:** Multiple bare `except Exception:` blocks silence errors without logging. This violates project rule #12 ("无裸异常捕获 — 必须指定异常类型，必须记录日志").

```python
# improvement_loop.py line 59-62
try:
    rt = fetch_realtime_quote(stock_code=stock)
    rt_price = rt.get("f43", 0) / 100
    if rt_price > 0:
        cur_price = rt_price
except Exception:
    pass  # Error swallowed with no logging
```

**Fix:** Log all exceptions with meaningful context.

```python
import logging
logger = logging.getLogger(__name__)

try:
    rt = fetch_realtime_quote(stock_code=stock)
    rt_price = rt.get("f43", 0) / 100
    if rt_price > 0:
        cur_price = rt_price
except Exception as e:
    logger.warning(f"实时行情获取失败 for {stock}: {e}")
```

---

### WR-03: Missing None guard for bollinger_upper in scoring

**File:** `core/scoring.py:120-128`
**Issue:** The code checks `bollinger_lower is not None` and `latest_close is not None`, but accesses `bollinger_upper` without a None guard. The `if result.bollinger_upper` truthiness check on line 121 would also fail if `bollinger_upper` is 0.0 (impossible for price but inconsistent).

```python
if result.bollinger_lower is not None and result.latest_close is not None:
    band_width = result.bollinger_upper - result.bollinger_lower if result.bollinger_upper else 1
```

In practice, bollinger bands are all set together in `_compute_bollinger`, but the defensive check should be consistent.

**Fix:** Add `bollinger_upper is not None` to the condition.

```python
if (result.bollinger_lower is not None and result.bollinger_upper is not None 
    and result.latest_close is not None):
    band_width = result.bollinger_upper - result.bollinger_lower
    if band_width > 0:
        position = (result.latest_close - result.bollinger_lower) / band_width
        # ...
```

---

### WR-04: Trend detection overly strict — requires 200 data points

**File:** `core/analyzers/technical.py:295`
**Issue:** Trend detection requires `len(close) >= MA_PERIODS[-1]` (200 data points). With fewer points, it returns `"unknown"`. However, MA20 and MA50 can provide useful trend signals with as few as 50 data points. This means users with limited history get no trend signal at all.

```python
if len(close) < MA_PERIODS[-1]:
    result.trend = "unknown"
    return
```

**Fix:** Implement tiered trend detection — use MA20 vs MA50 when MA200 is unavailable.

```python
if len(close) >= 50:  # MA20 + MA50 available
    if latest_20 > latest_50 > latest_200 if pd.notna(latest_200) else latest_20 > latest_50:
        result.trend = "up"
    elif latest_20 < latest_50 < latest_200 if pd.notna(latest_200) else latest_20 < latest_50:
        result.trend = "down"
    else:
        result.trend = "sideways"
elif len(close) >= 20:  # Only MA20 available
    # Simplified trend based on MA20 slope
    ...
```

---

### WR-05: Module-level filesystem side effect in prediction_tracker

**File:** `core/prediction_tracker.py:17`
**Issue:** Importing the module creates a directory on the filesystem. This violates the principle that module imports should be side-effect-free.

```python
TRACKER_DIR = Path(".prediction_history")
TRACKER_DIR.mkdir(parents=True, exist_ok=True)
```

This could cause issues in read-only environments, testing, or when the module is imported at application startup before the working directory is ready.

**Fix:** Lazily create the directory on first write.

```python
TRACKER_DIR = Path(".prediction_history")

def _ensure_dir() -> None:
    TRACKER_DIR.mkdir(parents=True, exist_ok=True)

def _save_records(stock_code: str, records: list[dict]) -> None:
    _ensure_dir()
    with open(_records_path(stock_code), "w") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
```

---

### WR-06: Reimplements RSI without using pandas_ta in market_context

**File:** `core/market_context.py:150-164`
**Issue:** The `_simple_rsi` function reimplements RSI calculation manually, despite the project convention (CLAUDE.md rule #16 — "不重复造轮子") specifying that technical indicators should use TA-Lib or pandas_ta. The market context module could use `pandas_ta.rsi()` on index data converted to a DataFrame.

Additionally, lines 157-159 use Python semicolons to combine statements on one line, which is non-idiomatic:
```python
gains.append(diff); losses.append(0)
```

**Fix:** Use pandas_ta for consistency, or at minimum remove the semicolons.

```python
def _simple_rsi(closes: list[float], period: int = 14) -> float:
    """Simple RSI calculation — used only for market index data."""
    import pandas as pd
    import pandas_ta as ta
    
    series = pd.Series(closes)
    rsi = ta.rsi(series, length=period, talib=False)
    if rsi is None or rsi.empty:
        return 50.0
    return float(rsi.iloc[-1])
```

---

### WR-07: Fragile MACD column name parsing in technical analyzer

**File:** `core/analyzers/technical.py:162-165`
**Issue:** The MACD column selection logic depends on the exact naming convention of pandas-ta output, which could change across versions. The combination of `startswith("MACD_")` and `"s" not in c.split("_")[-1] and "h" not in c.split("_")[-1]` is fragile and hard to understand.

```python
col_macd = [c for c in macd_df.columns if c.startswith("MACD_") and "s" not in c.split("_")[-1] and "h" not in c.split("_")[-1]]
col_signal = [c for c in macd_df.columns if "MACDs" in c]
col_hist = [c for c in macd_df.columns if "MACDh" in c]
```

**Fix:** Use a more explicit matching strategy — either match known column names or the last part of the column name after the parameter suffix.

```python
# Extract the MACD parameter suffix (e.g., "_12_26_9") that's common across all 3 columns
macd_cols = [c for c in macd_df.columns if c.startswith("MACD_") and not c[5:].startswith(("s_", "h_"))]
# Or better: match known pandas-ta output format
macd_cols = sorted([c for c in macd_df.columns if c.startswith("MACD_") and c.count("_") == 3 and not c.startswith(("MACDs_", "MACDh_"))])
```

---

## Info

### IN-01: Volume scoring uses ATR which is a volatility measure, not a volume metric

**File:** `core/scoring.py:150-152`
**Issue:** The `_score_volume` function checks `result.atr_14 is not None` as a condition for setting a baseline score of 55. ATR is a volatility measure, not a volume measure. Having ATR available shouldn't influence the volume score.

```python
if result.volume_sma_20 is not None and result.atr_14 is not None:
    score = 55.0
```

The ATR check seems like a proxy for "do we have enough data?" but it conflates data sufficiency with volume data availability. Use `result.volume_sma_20 is not None` alone, or check the data quality flag.

---

### IN-02: 5 yuan outlier threshold is absolute rather than relative

**File:** `core/prediction_tracker.py:77`
**Issue:** The outlier filter in `compute_accuracy` uses a fixed 5 yuan threshold. For BYD (trading around 90 yuan), this is ~5.5%. But for lower-priced stocks like 600567 (trading around 1.39 yuan), a 5 yuan deviation is 360%, so it would never filter anything. For higher-priced stocks in the future, it would be too aggressive.

```python
valid = [r for r in completed if abs(float(r["error"])) < 5.0]
```

**Fix:** Use a percentage-based threshold (e.g., 5% of current price).

```python
threshold = max(5.0, current_price * 0.05)  # 5 yuan or 5%, whichever is larger
# ... or derive it from ATR
```

---

### IN-03: scipy imported twice in valuation.py

**File:** `core/analyzers/valuation.py:35-36, 44-45`
**Issue:** `from scipy import stats` is imported inside each `if` block, meaning it runs twice when both PE and PB history are available. This is a minor performance concern (module-level `sys.modules` cache makes the actual load fast, but the import statement still executes twice).

**Fix:** Move the import to the top of the function or module level.

---

### IN-04: Duplicate import of statistics in get_calibration

**File:** `core/prediction_tracker.py:139`
**Issue:** `import statistics as _st` is imported inside the function body, shadowing the module-level `import statistics` (line 11). This is confusing and redundant.

```python
# Already imported at module level (line 11):
import statistics

# But re-imported inside function (line 139):
import statistics as _st
median_bias = _st.median([float(r["error"]) for r in filled])
```

**Fix:** Use the module-level import directly.

```python
median_bias = statistics.median([float(r["error"]) for r in filled])
```

---

### IN-05: stdout suppression pattern repeated throughout CLI

**Files:** `cli/main.py:127-132, 272-276, 301-316, 668-680, 808-834, 912-933`
**Issue:** The pattern of redirecting `sys.stdout` to `io.StringIO()` to suppress library debug output is repeated at least 6 times across the codebase. This is a fragile workaround — it captures all stdout output including legitimate errors, and it's easy to forget to restore stdout (though all current instances use try/finally).

The root cause should be fixed at the library level (suppress pandas-ta logging via `logging.getLogger("pandas_ta").setLevel(logging.WARNING)`) rather than patching stdout everywhere.

**Fix:** Add a one-time logger suppression at module level and remove all the stdout redirections.

```python
# In technical.py or main.py:
logging.getLogger("pandas_ta").setLevel(logging.WARNING)
logging.getLogger("ta").setLevel(logging.WARNING)
```

---

### IN-06: step9_verify in improvement loop does not actually verify

**File:** `cli/improvement_loop.py:218-223`
**Issue:** The "verify" step simply repackages data from step 1 rather than performing an independent verification. It reports the same score, direction, and action that were already printed, adding no new information or cross-validation.

```python
result["steps"]["9_verify"] = {
    "score": predict_result["score"],
    "direction": predict_result["direction"],
    "action": predict_result["action"],
}
```

**Fix:** Either remove this step as redundant, or implement actual verification (e.g., check that the prediction interval contains the current price if it's been 30+ minutes since prediction).

---

### IN-07: Missing type annotations on several functions

**Files:** `core/market_context.py:16,150`, `core/scoring.py:226`
**Issue:** Several functions lack return type annotations or have incomplete annotations, violating the project standard of "所有函数必须有" type annotations.

- `get_market_regime()` on line 16 returns `dict` but has no return type annotation
- `_simple_rsi()` on line 150 returns `float` but has only a bare annotation on closes
- `_trend_cn()` on line 226 of scoring.py is missing parameter type

**Fix:** Add complete type annotations.

```python
def get_market_regime() -> dict:
def _simple_rsi(closes: list[float], period: int = 14) -> float:
def _trend_cn(trend: str | None) -> str:
```

---

_Reviewed: 2026-06-17T08:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
