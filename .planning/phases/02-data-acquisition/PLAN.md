# Phase 2: 数据获取与缓存 ✅ DONE

**Status:** Complete | **Commit:** 2623ab9

## Deliverables

| File | Purpose |
|------|---------|
| `core/data_fetcher.py` | fetch_price_history, fetch_valuation_data, fetch_normalized_data, generate_mock_data |

## Architecture

```
AkShare API (or Mock) → CSV Cache (.cache/) → NormalizedData → downstream
```

- 缓存过期: 6 小时 (CACHE_MAX_AGE_HOURS)
- 复权模式: qfq 前复权
- 离线回退: generate_mock_data (500 天随机游走)
