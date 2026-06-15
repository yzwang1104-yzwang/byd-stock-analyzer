# ARCHITECTURE.md — 系统架构

**Project:** BYD Stock Analyzer
**Confidence:** HIGH

---

## 核心架构洞察

### 1. 数据归一化在边界层完成

pandas DataFrames（来自 AkShare，中文列名如 `收盘`、`开盘`）必须在进入分析模块前转换为纯 dataclass（`NormalizedData`、`PriceBar`）。这防止 DataFrame 列名耦合，并使核心逻辑无需 API 访问即可测试。

### 2. Phase 1 就是 Phase 2 的分析核心

通过强制 `core/` 中零 Django/CLI 导入，同一个 `analyzers/technical.py` 文件在 CLI 脚本和 Django view 中不变运行。Phase 间唯一变化的是数据缓存（内存→DB）和输出格式（Rich→HTML）。

### 3. 六边形（端口-适配器）模式

分析核心（`analyzers/`、`scoring.py`、`advice.py`）是纯计算，无 I/O。数据源（AkShare）和输出格式（CLI、HTML）是插在边缘的适配器。分析器可用 mock `NormalizedData` 独立测试。

### 4. 策略模式实现优雅演进

每个分析维度（技术、估值、情绪）是可插拔的 `BaseAnalyzer` 子类。失败的分析器优雅降级（流水线继续）。Phase 2/3 可添加新分析器而不触及现有代码。

### 5. 构建顺序 = 验证顺序

从底向上构建：数据合约→数据获取器→分析器→评分→建议→输出。每步在上一步之后产生可测试的输出。

---

## 组件和数据流

```
External API (AkShare 原始 JSON/DataFrame)
  → DataFetcher.normalize() → NormalizedData (dataclass, 纯类型)
    → TechnicalAnalyzer.analyze() → AnalysisResult (TypedDict of numbers)
    → ValuationAnalyzer.analyze() → AnalysisResult
      → ScoringEngine.compute() → ScoreResult (0-100 + 细项 + 信号)
        → AdviceEngine.generate() → AdviceResult (操作 + 仓位 + 推理)
          → CliOutputFormatter.format() → Rich格式字符串 (CLI)
          → Django template → HTML (Web)
```

**关键不变量：** 每个组件只依赖下层。分析器永不等同于 AkShare。评分永不分析原始数据。建议永不计算指标。输出永不做决策。

---

## Phase 1 构建顺序（按依赖）

| Step | 组件 | 产出 | 可验证？ |
|------|------|------|:---:|
| 1 | `core/models.py` (dataclass) | 系统共享词汇 | ✅ 单元测试 |
| 2 | `core/data_fetcher.py` | AkShare 数据，归一化 | ✅ 集成测试 |
| 3 | `core/analyzers/technical.py` | MA/MACD/RSI/布林/成交量 | ✅ mock 数据 |
| 4 | `core/analyzers/valuation.py` | PE/PB 分位，行业对比 | ✅ mock 数据 |
| 5 | `core/scoring.py` | 0-100 综合评分 | ✅ mock 数据 |
| 6 | `core/advice.py` | 买/卖/持 + 仓位% | ✅ mock 数据 |
| 7 | `core/config.py` | 默认权重、阈值 | 调参 |
| 8 | `output/cli_formatter.py` | Rich 终端输出 | ✅ |
| 9 | `cli/main.py` | 用户可以运行工具 | 🎯 **用户验证** |

**关键：** Step 3-6 可以在不调用 AkShare 的情况下完整开发和测试。Mock `NormalizedData` fixture 就够。

---

## Phase 迁移路径

| 迁移 | 怎么变 |
|------|--------|
| **Phase 1→2** (CLI→Django) | `core/` 整个目录不变导入；`data_fetcher.py` 加缓存层；新增 Django models/views |
| **Phase 2→3** (Web→SaaS) | 核心分析仍不变；新增 users/payments app；加 Redis 缓存；Celery 定时任务 |

**永远不变：** `core/analyzers/*.py`、`core/scoring.py`、`core/advice.py`

---

## 关键反模式

1. **DataFrame 跨越模块边界** — 立即归一化为 `NormalizedData`，不放过 pandas DataFrame
2. **"先做个原型 Phase 2 再重写"心态** — 你验证的是一个代码库，上线的是另一个
3. **入口点放业务逻辑** — Django views 和 CLI 脚本应该薄，调用 `services.run_analysis()`
4. **硬编码评分权重** — 权重必须可配置：`config.py`(P1)→Django settings(P2)→用户级(P3)
