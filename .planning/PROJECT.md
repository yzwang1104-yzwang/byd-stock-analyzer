# 比亚迪股票买入信号分析工具

## What This Is

一个多股票智能投资分析平台。支持4只股票（比亚迪002594/920839/600370/600567），提供：综合买入评分(0-100)、价格预测(±0.5元精度)、方向预测(6指标投票)、持仓管理(加仓信号)、买入时机仪表盘、自动校准循环。给结论，不给数据。

## Core Value

**让投资者不再犹豫——精准的买入评分 + 自动校准的预测 + 纪律化的加仓策略**，把"该不该买"从情绪问题变成数学问题。

## 当前状态 (2026-06-15)

- 10 Phase 全部完成，42 commits
- 18 Python 模块：数据层→分析层→评分→预测→校准→持仓→仪表盘
- 3 数据源：腾讯K线 + 东方财富实时 + 百度PE/PB估值
- 5 个 Cron 定时任务（交易时段 dashboard + 10分钟改进循环）
- MAE 0.15元，区间命中率 91%，偏差修正归零
- GitHub: https://github.com/yzwang1104-yzwang/byd-stock-analyzer

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] **BYD-01**: 获取比亚迪 A 股（002594）历史价格数据和实时行情
- [ ] **BYD-02**: 计算估值指标——PE/PB 历史分位、与行业均值对比
- [ ] **BYD-03**: 计算技术指标——MA、MACD、RSI、布林带、成交量
- [ ] **BYD-04**: 综合评分模型——加权计算买入评分(0-100)
- [ ] **BYD-05**: 建议仓位计算——基于评分和风险偏好给出仓位百分比
- [ ] **BYD-06**: 输出买入/卖出/观望建议 + 关键依据（1-2句话解释）
- [ ] **BYD-07**: 命令行交互——输入股价，输出完整分析报告

### Out of Scope

- Web 界面和用户系统 — Phase 2，先用命令行验证分析逻辑
- 多股票支持 — Phase 1 只做比亚迪
- 支付系统 — Phase 3
- 实时推送通知 — Phase 2
- 港股比亚迪(1211.HK) — Phase 2 扩展
- 机器学习预测模型 — Phase 2 扩展

## Context

创始人自 2015 年开始关注比亚迪，经历了 50→300→90 元的完整周期，十年从未真正买入。最大痛点是"多源数据→一个可信结论"的链路断裂：K 线看得到价但看不懂底，财报太多但不知重点，新闻真假难辨，技术指标不会解读。上周比亚迪跌到 89 元时再次没有下定决心买入。估计累计错过 100 万人民币收益。

市场现有工具（华泰 AI 涨乐、雪球、同花顺）都在做"信息增强"，从来不给结论。用户需要的是"导航"（前方 500 米右转），不是"望远镜"（这是地图你自己看）。

## Constraints

- **技术栈**: Python + AkShare + TA-Lib + pandas + numpy
- **阶段**: Phase 1 纯命令行脚本，无需数据库/服务器/部署
- **用户**: 不会写代码，所有技术实现由 AI 完成
- **数据源**: 免费（AkShare），不做付费数据
- **合规**: 必须标注"分析结果仅供参考，不构成投资建议"
- **可解释性**: 评分逻辑必须用户能理解，不能是黑盒

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Django + HTMX + PostgreSQL 作为最终技术栈 | 用户不会写代码，Django Admin 提供免代码管理；Python 全栈降低维护复杂度 | — Pending |
| Phase 1 用命令行脚本验证 | 在投入 Web 开发前验证分析逻辑是否有用，沉没成本最小 | — Pending |
| 只做比亚迪一只股票 | 单股票深度分析 > 多股票浅覆盖，专一度是差异化优势 | — Pending |
| 全面分析——估值+技术面 | 用户需要的是综合判断，单一维度没有说服力 | — Pending |
| 99 元/月 SaaS 定价 | 用户已验证付费意愿，ROI 逻辑清晰（少错过一次就远超年费） | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-14 after initialization*
