# Phase 1: 项目基础与配置 ✅ DONE

**Status:** Complete | **Date:** 2026-06-15 | **Commit:** 4d88583

## Goal
建立项目骨架——共享数据结构、可配置参数、零框架依赖的 core 模块。

## Deliverables

| File | Purpose |
|------|---------|
| `core/models.py` | 7 dataclass: PriceBar, NormalizedData, ValuationData, AnalysisResult, ScoreBreakdown, ScoreResult, AdviceResult |
| `core/config.py` | ScoringConfig, DEFAULT_WEIGHTS (5-factor 35+30+20+10+5), SCORE_THRESHOLDS |
| `pyproject.toml` | Package metadata, all Phase 1-7 dependencies |
| `requirements.txt` | Pinned core + dev dependencies |
| `.gitignore` | Python standard ignores |

## Key Decisions
- **六边形端口适配器**: core/ 零 Django/CLI 导入，纯 dataclass 跨 Phase 复用
- **TRADE-OFF**: 不做 ML 黑盒 → 加权多因子可解释模型
- **TRADE-OFF**: 暂不装 TA-Lib → pandas-ta 纯 Python 回退
