# 比亚迪股票买入信号分析工具

## What This Is

一个帮助个人投资者判断比亚迪(BYD, 002594)买入时机的分析工具。输入当前股价，输出综合买入评分(0-100)、建议仓位和建议操作。给结论，不给数据——"现在能不能买"一句话回答。

## Core Value

**给出一个可信的买入/卖出结论，让用户可以跟着操作**——不是提供一堆技术指标让用户自己分析。

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
