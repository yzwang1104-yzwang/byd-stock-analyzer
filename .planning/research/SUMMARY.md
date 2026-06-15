# RESEARCH SUMMARY — 比亚迪股票分析工具

**Synthesized:** 2026-06-14
**Sources:** STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md

---

## Executive Summary

**产品定位：结论优先的股票分析工具，不是数据仪表盘。** 核心价值 = 把原始市场数据转化为单一可操作评分（0-100）+ 推理 + 仓位建议。用户要的是导航系统，不是地图。

**三阶段交付：**
- Phase 1: CLI Python 脚本（2-3天）— 验证评分模型
- Phase 2: Django Web 仪表盘（1-2周）— 同一核心 + 浏览器界面
- Phase 3: SaaS 订阅（4-6周）— 变现+扩展

---

## Top 5 关键发现

1. **AkShare 是唯一免费 A 股数据源** — 覆盖价格+财报+估值；需 qfq 复权+CSV 缓存
2. **TA-Lib + pandas-ta 是技术指标标配** — TA-Lib 提供计算、pandas-ta 提供 Pythonic 封装
3. **六边形架构确保 Phase 1→2 无重写** — core/ 零 Django/CLI 导入，纯计算独立于 I/O
4. **前瞻偏差是最大技术风险** — `shift(1)` + 单元测试从第一天就必须正确
5. **"狼来了"陷阱是最大信任风险** — 下跌趋势中估值越来越"便宜"导致重复买入信号

---

## 跨维度模式和冲突

| 发现 | STACK | FEATURES | ARCHITECTURE | PITFALLS |
|------|:---:|:---:|:---:|:---:|
| 不做 ML/黑盒 | ✅ | ✅ | — | ✅ |
| 可解释性优先 | ✅ 加权评分 | ✅ 1行结论 | — | ✅ |
| 数据层抽象 | ✅ 接口隔离 | — | ✅ 端口适配器 | ✅ 避免单点故障 |
| 卖出信号必要 | — | — | — | ✅ Phase 1 必须包含 |
| 三层分离 | — | — | ✅ data/analysis/output | ✅ 防止 CLI→Web 重写 |

**一致结论：** 四个维度高度一致。同一个答案从技术栈、功能、架构、坑点角度反复出现——**Phase 1 就是 Phase 2 的分析核心，不是什么扔掉的原型。**

---

## 路线图影响

### Phase 1 — CLI 验证器（2-3天）
- 构建顺序（9步）：models → data_fetcher → technical analyzer → valuation analyzer → scoring → advice → config → CLI formatter → entry point
- 必须预防：前瞻偏差、数据质量、虚假精度、确认偏差、信息过载
- 必须包含：基础卖出触发（RSI>70 + PE>80分位）
- 研究需求：SKIP（成熟模式）

### Phase 2 — Web 仪表盘（1-2周）
- core/ 整个目录不变导入
- 新增：Django models、信号历史追踪、ECharts K线图、邮件推送
- 关键坑：缓存层、冷却期、历史信号可视化建立信任

### Phase 3 — SaaS 平台（4-6周）
- 法律审查是付费层级的前置门（CSRC 法规）
- 多股票扩展解决单股票留存风险
- Stripe/支付宝支付、Celery 定时任务

---

## 5 个待解决缺口

1. **评分校准方法论** — 强买/买入/观望/卖出边界未定义
2. **AkShare 备用源** — Baostock 太弱、tushare 需注册、yfinance 无 A 股
3. **卖出信号完整性** — 冲突解决（如超买但 PE 便宜怎么判）
4. **单股票 vs 多股票架构** — 从第一天就让 data_fetcher 接受任意股票代码
5. **用户研究太窄** — 所有发现来自一个用户（创始人）；Phase 2 前需 3+ 用户访谈

---

## 置信度评估

| 维度 | 置信度 | 原因 |
|------|:---:|------|
| 技术栈 | MEDIUM-HIGH | 组合成熟，AkShare 稳定性是风险 |
| 功能 | MEDIUM | 标配功能清楚；差异化来自缺口分析 |
| 架构 | HIGH | 教科书模式，依赖推导的构建顺序 |
| 坑点 | MEDIUM | 金融文献清晰；CSRC 法律风险未验证 |
