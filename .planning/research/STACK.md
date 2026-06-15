# STACK.md — 技术栈研究

**Project:** BYD Stock Analyzer (Phase 1: CLI Python 脚本)
**Confidence:** MEDIUM

---

## Recommended Stack

| Layer | 推荐 | 版本 | 理由 |
|-------|------|------|------|
| Language | Python | 3.11+ | 最广库兼容性 |
| Data acquisition | AkShare | 1.14+ | 唯一免费覆盖价格+财报+估值的 A 股数据源 |
| Data manipulation | pandas + numpy | 2.2+ / 1.26+ | 时序数据必备 |
| Technical indicators | TA-Lib + **pandas-ta** | 0.6+ / 0.3.14b0 | 行业标准 + Pythonic 封装层 |
| Valuation | scipy + custom code | 1.13+ | 无现成库覆盖中国会计准则 |
| Scoring | 自定义加权模型 | — | 必须可解释，不做 ML |
| CLI | rich + typer | 13.x / 0.12+ | 专业终端输出 |
| Testing | pytest | 8.x | 行业标准 |
| Linting | ruff | 0.5+ | 一个工具替代 flake8+isort+black |

---

## 关键发现

### 1. 数据获取：AkShare 是唯一可行选择

A 股数据没有好的替代方案。AkShare 免费、无需注册、无需 API Key，从一个源覆盖历史价格 + 财务报表 + 估值数据。

**Phase 1 关键 API：**
- `stock_zh_a_hist(symbol="002594", period="daily")` → OHLCV + 成交量
- `stock_a_pe(symbol="002594")` → 历史 PE/PB（估值分位）
- `stock_a_lg_indicator()` → 行业 PE/PB 均值（同行对比）
- `stock_zh_a_gdhs()` → 股东人数变化（情绪信号）

**风险：** AkShare 依赖第三方财经网站。当网站改版时 API 会中断（通常 24-72 小时修复）。缓解：激进缓存到 CSV，仅在过期时重新获取。

### 2. 技术指标：TA-Lib + pandas-ta 双层

TA-Lib 是 80+ 技术指标的行业标准。Windows 安装有已知困难（C 库编译），但预编译 wheel 现已可用。如果安装失败，pandas-ta 有纯 Python 回退，覆盖 Phase 1 80% 需求。

**pandas-ta 不是可选项** — 它把 TA-Lib 封装为 pandas DataFrame 扩展（`df.ta.rsi(length=14, append=True)` 添加 `RSI_14` 列），大幅提升代码可读性。

**评分所需指标：** SMA(20/50/200), RSI(14), MACD(12/26/9), 布林带(20,2), ATR(14), 成交量 SMA(20)。

### 3. 估值分析：无现成库覆盖中国会计准则

美国估值库（financedata 等）假设 US GAAP。中国会计准则在政府补贴处理、关联方披露、报表格式等方面不同。

**建议：** 在专用 `valuation.py` 模块中从原始 AkShare 数据构建估值逻辑。用 `scipy.stats.percentileofscore()` 计算历史 PE/PB 百分位。

### 4. 评分引擎：加权多因子，非 ML

**推荐因子权重：**
| 因子 | 权重 | 理由 |
|------|------|------|
| 估值 | 35% | 比亚迪是周期股，估值最重要 |
| 技术 | 30% | 动量+超卖信号 |
| 趋势 | 20% | 均线结构 |
| 成交量 | 10% | 价格变动确认 |
| 情绪 | 5% | 辅助信号 |

**分数→建议映射：** 0-30=卖出, 31-55=观望, 56-75=可考虑, 76-90=建议买入, 91-100=强烈买入。仓位用 quarter-Kelly 准则。

---

## 绝对不用

| 技术 | 原因 |
|------|------|
| scikit-learn, xgboost, lightgbm | ML 过早，且违反可解释性要求 |
| backtrader, zipline | 回测框架，100+ 依赖，对评分过重 |
| plotly, matplotlib | CLI 输出无价值，Phase 2 用 ECharts |
| django, flask, fastapi | Phase 1 是 CLI，Web 框架零价值 |
| celery, redis | Phase 1 无后台任务 |
| tushare | 需注册/API Key，违反免费数据约束 |
| baostock | 估值分析能力太弱 |

## 关键反模式

1. **一个巨大的 main.py** — 必须分离关注点：data_fetcher / technicals / valuation / scoring / output
2. **不缓存数据** — AkShare 调用慢（3-5秒/API）。缓存到 CSV，仅在过期时重新获取
3. **硬编码股票代码** — 用单一常量 `STOCK_CODE = "002594"`，Phase 2 加港股时改一处即可
