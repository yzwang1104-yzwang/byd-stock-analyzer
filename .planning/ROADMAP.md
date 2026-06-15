# ROADMAP.md — 比亚迪股票分析工具

**Generated:** 2026-06-15
**Granularity:** Fine (7 phases)
**Coverage:** 33/33 v1 + 3 extended phases (prediction system)

---

## Phase Map

| # | Phase | Goal | REQs | Plans |
|---|-------|------|------|-------|
| 1 | 项目基础与配置 | 共享数据结构 + 可配置参数 | SCOR-05 | 2 |
| 2 | 数据获取与缓存 | AkShare 获取并缓存比亚迪数据 | DATA-01~05 | 3 |
| 3 | 技术指标计算 | 6 大技术指标 + 前瞻防护 | TECH-01~07 | 2 |
| 4 | 估值分析 | PE/PB 分位 + 行业对比 | VALU-01~04 | 2 |
| 5 | 评分引擎 | 加权综合评分 + 偏差防护 | SCOR-01,02,06,07 | 2 |
| 6 | 决策逻辑与信号 | 操作建议 + 仓位 + 卖出信号 | SCOR-03,04, SELL-01,02 | 2 |
| 7 | CLI 输出与合规 | 专业终端输出 + 合规 | OUT-01~05, COMP-01~03 | 2 |
| 8 | 价格预测系统 | ATR预测 + 记录 + 校准 | — | 2 |
| 9 | 方向预测+回测 | 6指标投票 + 300天回测 | — | 2 |
| 10 | 自动校准+调度 | 自动回填 + Cron + 警报 | — | 2 |
| 11 | Django Web 仪表盘 | ECharts K线 + 多股票 + 持仓管理 | WEB-01~06 | 3 |
| 12 | 部署上线 | Docker + 阿里云 + PostgreSQL | DEP-01~06 | 3 |
| 13 | 移动端通知 | 微信推送 + 早报 + 加仓提醒 | MOB-01~04 | 2 |

**Dependency chain:** 1 → ... → 10 → 11 → 12 → 13

---

## Phase Details

### Phase 1: 项目基础与配置
**Goal:** 建立项目骨架——共享数据结构、可配置参数、零框架依赖的 core 模块

| REQ-ID | Requirement |
|--------|-------------|
| SCOR-05 | 评分权重通过 config.py 可配置 |

**Success Criteria:**
1. `pip install -e .` 成功安装项目及所有依赖
2. `core/models.py` 定义 NormalizedData / AnalysisResult / ScoreResult / AdviceResult dataclass
3. `core/config.py` 包含可配置的评分权重字典，运行时可加载
4. Core 模块零 CLI/Django 依赖——可被任何入口点导入
5. 项目目录结构清晰，每个模块有 __init__.py

---

### Phase 2: 数据获取与缓存
**Goal:** 从 AkShare 获取比亚迪数据，归一化并缓存到 CSV

| REQ-ID | Requirement |
|--------|-------------|
| DATA-01 | 获取 002594 历史日线 OHLCV + 成交量，使用 qfq |
| DATA-02 | 获取历史 PE/PB 估值数据 |
| DATA-03 | 获取行业 PE/PB 均值数据 |
| DATA-04 | 缓存到本地 CSV，标注时间戳，过期自动重取 |
| DATA-05 | data_fetcher 接受任意股票代码参数 |

**Success Criteria:**
1. 成功获取比亚迪 3 年+历史日线数据（qfq 复权）
2. PE/PB 历史数据和行业均值成功获取
3. CSV 缓存带时间戳，再次运行时显示 "(cached)" 标识
4. `data_fetcher.fetch("002594")` 和 `data_fetcher.fetch("000001")` 都能工作
5. 过期缓存自动触发重新获取

---

### Phase 3: 技术指标计算
**Goal:** 计算全部 6 大技术指标，内置前瞻偏差防护

| REQ-ID | Requirement |
|--------|-------------|
| TECH-01 | SMA(20/50/200) 移动均线 |
| TECH-02 | MACD(12/26/9) 金叉/死叉 |
| TECH-03 | RSI(14) 超买/超卖 |
| TECH-04 | 布林带(20,2) |
| TECH-05 | ATR(14) 波动率 |
| TECH-06 | 成交量 SMA(20) |
| TECH-07 | shift(1) 防止前瞻偏差 |

**Success Criteria:**
1. 6 个指标全部计算为结构化 AnalysisResult
2. MACD 正确识别金叉/死叉交叉点
3. RSI 正确标记超买(>70)/超卖(<30)区域
4. 逐行验证 shift(1)——信号日 T 的值不包含 T 日数据
5. 模块纯 DataFrame-in/DataFrame-out，无副作用

---

### Phase 4: 估值分析
**Goal:** 计算 PE/PB 历史分位和行业相对估值判断

| REQ-ID | Requirement |
|--------|-------------|
| VALU-01 | PE 历史百分位（scipy.stats.percentileofscore） |
| VALU-02 | PB 历史百分位 |
| VALU-03 | 行业 PE/PB 均值对比 → 低估/合理/高估 |
| VALU-04 | 数据不可用时优雅降级 |

**Success Criteria:**
1. PE 百分位计算正确（与手动计算交叉验证）
2. PB 百分位计算正确
3. 输出明确的相对估值判断（低估/合理/高估）
4. AkShare 估值数据不可用时给出降级提示但不阻断流程

---

### Phase 5: 评分引擎
**Goal:** 加权综合评分 0-100 + 偏差防护

| REQ-ID | Requirement |
|--------|-------------|
| SCOR-01 | 5 因子加权模型——估值(35%)+技术(30%)+趋势(20%)+成交量(10%)+情绪(5%) |
| SCOR-02 | 整数评分 0-100，带置信度（高/中/低） |
| SCOR-06 | 看跌因子防止确认偏差——必须能在看跌条件下输出卖出分数 |
| SCOR-07 | 信号冷却——两次买入信号间隔 ≥ N 个交易日 |

**Success Criteria:**
1. 加权评分输出为 0-100 整数（非浮点精度）
2. 置信度标注基于数据可用性和指标一致性
3. 在下跌趋势（如比亚迪 2022 年走势）中正确给出低分而非假买入
4. 连续两个交易日不重复发出买入信号（冷却期生效）
5. 纯函数——输入 AnalysisResult，输出 ScoreResult，无 I/O

---

### Phase 6: 决策逻辑与信号
**Goal:** 分数映射到操作建议 + 仓位计算 + 卖出信号

| REQ-ID | Requirement |
|--------|-------------|
| SCOR-03 | 5 档映射——0-30/31-55/56-75/76-90/91-100 |
| SCOR-04 | 4 档仓位——25%/50%/75%/100% |
| SELL-01 | 卖出触发——RSI>70 且 PE>80%分位 |
| SELL-02 | 卖出信号输出评分+降仓位+依据 |

**Success Criteria:**
1. 5 档操作建议映射正确（0-30→卖出, 31-55→观望, 56-75→考虑, 76-90→建议买入, 91-100→强烈买入）
2. 仓位计算纳入 ATR 波动率调整（高波动→降仓位）
3. RSI>70 且 PE>80%分位时触发卖出信号
4. 每个决策附带一句可解释依据（如"RSI 超卖 + PE 处于历史低位"）

---

### Phase 7: CLI 输出与合规
**Goal:** 专业 Rich 格式化终端输出 + 完整合规

| REQ-ID | Requirement |
|--------|-------------|
| OUT-01 | 一行结论——评分+操作+仓位+依据 |
| OUT-02 | Rich 彩色面板+结构化表格 |
| OUT-03 | --verbose 展开详细指标数值 |
| OUT-04 | --price 命令行参数 |
| OUT-05 | 信号时效提示——"24小时内决策" |
| COMP-01 | 强制免责声明 |
| COMP-02 | 非命令式措辞 |
| COMP-03 | 不承诺收益/不给目标价 |

**Success Criteria:**
1. `python cli/main.py --price 89` 输出一行结论
2. Rich 格式化面板正确渲染（彩色+表格）
3. `--verbose` 展开所有 6 大指标的详细数值
4. 输出包含时效性提示
5. 每页输出底部强制显示免责声明
6. 全输出搜索不到"建议买入""目标价""预计收益"等措辞
7. 用户做盲测——只看输出就知道该做什么而不需要翻数据

---

## Coverage Validation

```
Phase 1: SCOR-05
Phase 2: DATA-01 DATA-02 DATA-03 DATA-04 DATA-05
Phase 3: TECH-01 TECH-02 TECH-03 TECH-04 TECH-05 TECH-06 TECH-07
Phase 4: VALU-01 VALU-02 VALU-03 VALU-04
Phase 5: SCOR-01 SCOR-02 SCOR-06 SCOR-07
Phase 6: SCOR-03 SCOR-04 SELL-01 SELL-02
Phase 7: OUT-01 OUT-02 OUT-03 OUT-04 OUT-05 COMP-01 COMP-02 COMP-03

Mapped: 33/33 ✓  No orphans ✓  No duplicates ✓
```

## Design Principles

- **可复用性:** Phase 1-6 产出的 `core/` 模块纯计算，Phase 7 CLI 是唯一的终端耦合层。Phase 2 Django 直接导入 Phase 1-6
- **依赖链:** 严格线性，无循环依赖
- **可测试性:** 每个 Phase 产出结构化数据工件，可独立单元测试
- **自然边界:** 类别（DATA/TECH/VALU/SCOR/SELL/OUT/COMP）干净映射到 Phase

---
*Last updated: 2026-06-15 after roadmap creation*
