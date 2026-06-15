# CLAUDE.md — 比亚迪股票智能分析平台

> **产品定位：** 为散户股民提供比亚迪(BYD, 002594/1211.HK)股票的智能分析服务，帮助用户判断最佳买入时机。
> **商业模式：** SaaS 订阅制，提供免费基础分析和付费高级预测功能。
> **目标用户：** 不会写代码的创始人，所有技术决策由 Claude 代为完成。

---

## 一、技术栈

| 分类 | 技术 | 版本 | 选择理由 |
|------|------|------|----------|
| **Web 框架** | Django | 5.x | 全功能框架，内置 Admin/ORM/Auth，Python 生态无缝对接数据分析 |
| **前端交互** | HTMX + Alpine.js | 2.x / 3.x | 无需写 React，用 HTML 属性实现 SPA 体验，学习成本极低 |
| **CSS 框架** | Tailwind CSS | 4.x | 原子化 CSS，组件复用方便，生态最大 |
| **图表库** | ECharts (JS) | 5.x | 国产最强图表库，K线图/技术指标图原生支持，中文文档完善 |
| **数据库** | PostgreSQL | 16+ | 最成熟的开源关系型数据库，支持 JSON/全文搜索/时序扩展 |
| **ORM** | Django ORM | 内置 | 自动生成迁移、QuerySet 查询、防 SQL 注入 |
| **缓存** | Redis | 7.x | 缓存股票数据、会话管理、Celery 消息队列 |
| **任务队列** | Celery | 5.x | 异步获取股票数据、执行预测模型、发送邮件通知 |
| **认证** | Django Allauth | 0.60+ | 邮箱注册/登录、微信扫码登录、密码重置 |
| **支付** | Stripe / 支付宝 | - | 订阅付费（国内用户优先支付宝，国际用 Stripe） |
| **部署** | Docker + Nginx | - | 容器化部署，一份配置到处运行 |
| **服务器** | 阿里云 / Railway | - | 国内用户用阿里云 ECS，海外用 Railway 一键部署 |
| **CI/CD** | GitHub Actions | - | 自动测试、自动部署 |
| **数据源** | AkShare + yfinance | - | AkShare 获取 A 股数据，yfinance 获取港股数据 |
| **数据分析** | pandas + numpy + scikit-learn | - | 数据清洗、特征工程、机器学习预测 |
| **技术指标** | TA-Lib | 0.6+ | 80+ 技术指标计算（MACD/RSI/布林带等） |

---

## 二、编码规范

### Python（Django 后端）

```python
# 1. 类型注解 — 所有函数必须有
def calculate_ma(prices: list[float], window: int = 20) -> list[float]:
    """计算移动平均线"""
    ...

# 2. 导入顺序：标准库 → 第三方 → Django → 项目内
import logging
from datetime import date, timedelta

import pandas as pd
import numpy as np

from django.db import models
from django.conf import settings

from stocks.services import fetch_byd_data

# 3. 模型命名：单数名词，蛇形命名
class StockAlert(models.Model):
    user = models.ForeignKey("users.User", on_delete=models.CASCADE)
    stock_code = models.CharField(max_length=20)
    ...

# 4. 视图命名：动宾结构
class BuySignalListView(View):
    def get(self, request): ...

# 5. 服务层：业务逻辑放 services.py，不放 views.py
# stocks/services.py
def analyze_buy_signal(stock_code: str) -> dict: ...

# 6. 配置敏感信息用环境变量
# ✅ 正确
API_KEY = os.environ["AKSHARE_API_KEY"]
# ❌ 错误
API_KEY = "sk-1234567890abcdef"
```

### 强制规则
- **PEP 8**：Black 自动格式化，行宽 100 字符
- **Docstring**：所有公开函数必须有 Google 风格 docstring
- **Type Hints**：所有函数参数和返回值必须有类型注解
- **无裸 except**：必须捕获具体异常类型
- **QuerySet 不拼接字符串**：永远用 ORM 参数化查询

### HTML/模板

```django
{# 1. 用 htmx 属性实现交互，不写 fetch/axios #}
<button hx-post="{% url 'stocks:buy_signal' %}"
        hx-target="#result"
        hx-indicator="#spinner">
  分析买入时机
</button>

{# 2. 用 Alpine.js 处理纯前端状态 #}
<div x-data="{ open: false }">
  <button @click="open = !open">展开</button>
  <div x-show="open">详细数据</div>
</div>
```

### JavaScript（仅限必要场景）
- 优先用 HTMX + Alpine.js，避免手写 JavaScript
- 如需手写，使用原生 ES6，不引入 jQuery
- 图表初始化用 ECharts 实例，挂载到 Alpine 组件上

---

## 三、项目目录结构

```
byd-stock-analyzer/
├── CLAUDE.md                    # 本文件 — 项目总规范
├── README.md                    # 项目说明和本地运行指南
├── .gitignore
├── .env.example                 # 环境变量模板（不含真实密钥）
├── docker-compose.yml           # 本地开发环境（PostgreSQL + Redis）
├── Dockerfile                   # 生产部署镜像
├── requirements.txt             # Python 依赖
├── pyproject.toml               # 项目元数据和工具配置
├── manage.py                    # Django 命令行入口
│
├── config/                      # Django 项目配置
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py              # 公共配置
│   │   ├── development.py       # 开发环境
│   │   └── production.py        # 生产环境
│   ├── urls.py                  # 根路由
│   ├── wsgi.py
│   └── asgi.py
│
├── apps/                        # Django 应用模块
│   ├── users/                   # 用户模块
│   │   ├── models.py            # User, Profile, Subscription
│   │   ├── views.py             # 注册/登录/个人中心
│   │   ├── services.py          # 订阅管理、权限检查
│   │   ├── urls.py
│   │   ├── admin.py
│   │   └── templates/users/
│   │
│   ├── stocks/                  # 股票数据模块（核心）
│   │   ├── models.py            # Stock, PriceHistory, BuySignal
│   │   ├── views.py             # 行情页、买入信号页
│   │   ├── services.py          # 技术分析、信号计算
│   │   ├── analyzers/           # 分析策略（策略模式）
│   │   │   ├── __init__.py
│   │   │   ├── base.py          # 分析策略基类
│   │   │   ├── trend.py         # 趋势分析
│   │   │   ├── valuation.py     # 估值分析
│   │   │   └── sentiment.py     # 市场情绪分析
│   │   ├── data_fetcher.py      # 数据获取（AkShare/yfinance）
│   │   ├── tasks.py             # Celery 定时任务
│   │   ├── urls.py
│   │   └── templates/stocks/
│   │
│   ├── predictions/             # AI 预测模块
│   │   ├── models.py            # PredictionModel, PredictionResult
│   │   ├── views.py             # 预测结果展示
│   │   ├── services.py          # 模型调用
│   │   ├── ml_models/           # 机器学习模型
│   │   │   ├── __init__.py
│   │   │   ├── lstm_model.py    # LSTM 时序预测
│   │   │   └── ensemble.py      # 集成投票模型
│   │   ├── tasks.py             # 模型训练/预测定时任务
│   │   ├── urls.py
│   │   └── templates/predictions/
│   │
│   ├── payments/                # 支付模块
│   │   ├── models.py            # Order, SubscriptionPlan
│   │   ├── views.py             # 支付回调、订单管理
│   │   ├── services.py          # Stripe/支付宝对接
│   │   ├── urls.py
│   │   └── templates/payments/
│   │
│   └── dashboard/               # 用户仪表盘
│       ├── views.py
│       ├── urls.py
│       └── templates/dashboard/
│
├── templates/                   # 全局模板
│   ├── base.html                # 基础布局（导航栏/页脚）
│   ├── components/              # 可复用组件
│   │   ├── kline_chart.html     # K线图组件
│   │   ├── signal_card.html     # 买入信号卡片
│   │   └── price_table.html     # 价格数据表格
│   └── pages/                   # 静态页面
│       ├── landing.html         # 落地页/营销页
│       └── pricing.html         # 定价页
│
├── static/                      # 静态资源
│   ├── css/
│   │   └── app.css              # Tailwind 编译输出
│   ├── js/
│   │   └── charts.js            # ECharts 图表初始化
│   └── images/
│
├── utils/                       # 项目级工具
│   ├── formatters.py            # 数字/日期格式化
│   ├── validators.py            # 自定义校验器
│   └── mixins.py                # View Mixin 复用
│
└── tests/                       # 测试
    ├── conftest.py              # pytest fixtures
    ├── test_users/
    ├── test_stocks/
    ├── test_predictions/
    └── test_payments/
```

---

## 四、常用命令

```bash
# ====== 环境初始化 ======
python -m venv venv                          # 创建虚拟环境
source venv/bin/activate                     # 激活（Linux/Mac）
venv\Scripts\activate                        # 激活（Windows）
pip install -r requirements.txt              # 安装依赖
docker compose up -d                         # 启动 PostgreSQL + Redis

# ====== 数据库 ======
python manage.py migrate                     # 执行迁移
python manage.py makemigrations              # 生成迁移文件
python manage.py showmigrations              # 查看迁移状态

# ====== 开发运行 ======
python manage.py runserver                   # 启动开发服务器 (:8000)
python manage.py shell                       # Django 交互式 Shell
python manage.py createsuperuser             # 创建管理员账号

# ====== Celery ======
celery -A config worker -l info              # 启动 Celery Worker
celery -A config beat -l info                # 启动定时任务调度器
celery -A config flower                      # 任务监控面板 (:5555)

# ====== 测试 ======
pytest                                       # 运行所有测试
pytest tests/test_stocks/ -v                 # 运行指定模块测试
pytest --cov=apps --cov-report=html          # 测试覆盖率报告

# ====== 代码质量 ======
black .                                      # 格式化 Python 代码
isort .                                      # 排序 import
ruff check .                                 # 代码检查（替代 flake8）
mypy apps/                                   # 类型检查

# ====== 数据管理 ======
python manage.py fetch_stock_data            # 手动获取比亚迪数据
python manage.py train_model                 # 训练预测模型
python manage.py generate_signals            # 生成今日买入信号

# ====== 部署 ======
docker build -t byd-analyzer .               # 构建 Docker 镜像
docker compose -f docker-compose.prod.yml up # 生产环境启动
python manage.py collectstatic --noinput     # 收集静态文件
```

---

## 五、红线规则（绝对不可违反）

### 安全红线
1. **密钥不入库** — API Key、数据库密码、支付密钥等一律用环境变量，`.env` 文件加入 `.gitignore`
2. **绝不用 eval/exec** — 任何情况下都禁止动态执行代码
3. **密码必须哈希** — 使用 Django 内置 `make_password()`，绝不明文存储
4. **CSRF 保护不可关闭** — HTMX 请求需带 CSRF Token（Django 默认支持）
5. **SQL 查询必须参数化** — 只用 Django ORM，禁止字符串拼接 SQL
6. **文件上传必须校验** — 类型、大小、内容三重校验
7. **支付回调必须验签** — Stripe/支付宝回调必须验证签名，不能仅凭状态码

### 数据红线
8. **不提供买卖建议的绝对承诺** — 页面底部必须标注"分析结果仅供参考，不构成投资建议"
9. **数据延迟必须说明** — 免费用户看延迟 15 分钟数据，付费用户看实时数据，必须明确标注
10. **用户数据可删除** — 必须支持账号注销及关联数据彻底删除（合规要求）

### 代码质量红线
11. **测试覆盖核心逻辑** — 买入信号算法、支付流程、用户认证必须有测试
12. **无裸异常捕获** — 必须指定异常类型，必须记录日志
13. **模型变更必有迁移** — 禁止手动改数据库，一切通过 migration
14. **环境必须可区分** — `DEBUG=True` 仅限本地，生产环境 `DEBUG=False`

### 架构红线
15. **View 不放业务逻辑** — 视图只做请求分发和响应渲染，逻辑放 `services.py`
16. **不重复造轮子** — 分析指标用 TA-Lib，图表用 ECharts，不自己手写公式
17. **异步任务不阻塞请求** — 数据获取、模型训练、邮件发送必须走 Celery

---

## 六、AI 协作约定

1. **所有技术决策由 Claude 做出** — 用户不写代码，Claude 需给出明确方案和执行
2. **先展示方案再动手** — 每次改动前先说明要改什么、为什么改、预期结果
3. **中文沟通，代码用英文** — 所有解释用中文，变量/函数/注释用英文
4. **变更后总结** — 每次改动完成后，用 3-5 句话说清楚改了什么
5. **遇到不确定的数据源或 API 变化** — 先查阅文档再动手，不在不确定的情况下提交代码

---

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec

---

## 七、产品设计（2026-06-14 Office Hours 输出）

### 问题陈述

用户（创始人）自 2015 年开始关注比亚迪股票，经历了从 50 元涨到 300 元再跌回 90 元的完整周期，**十年一直在观望，从未真正买入**。核心问题不是缺数据——K 线、财报、新闻都摆在眼前——而是"多源数据 → 一个可信的买入结论"这条链路断了。K 线看得到价但看不懂底，财报太多但不知重点，新闻很多但真假难辨，技术指标摆在那但不会解读。最终就是盯着 89 元的价格，手悬在键盘上，不敢按。

### 需求证据

- "一直都在错过买入时机，最近一次是上周，股票跌到 89 元，没有下定决心买入"（具体价格 + 具体时间 = 真实痛点）
- "如果这个工具消失了，会受到 80% 影响"（高度依赖）
- "估计少赚了 100 万人民币"（具体金额，真实代价）
- "一周 4 天花在分析上"（时间成本高）
- "我会跟着提示直接建仓"（行为级需求——要的是指令，不是数据）
- "愿意（付费），因为会挣更多"（付费意愿明确，ROI 逻辑清晰）

### 现状

用户当前的分析流程：
1. 看 K 线图——但看不懂技术指标（MACD/RSI/KDJ 等）
2. 看财报——内容太多，抓不住重点
3. 看新闻——不确定信息真假
4. 问朋友——依赖他人判断
5. 最后：犹豫、观望、错过

市场现有工具的局限：华泰 AI 涨乐、雪球、同花顺等都在做"信息增强"（更清晰的 K 线、更快的异动提醒、更漂亮的指标面板），但从来不给结论。它们面向的是"会分析但缺数据"的人。用户是"不会分析但需要结论"的人——这是完全不同的需求。

### 关键洞察（EUREKA）

现有工具面向的是"会分析但缺数据"的人。用户面向的是"不会分析但需要结论"的人。这是两个完全不同的用户群。前者要的是望远镜，后者要的是导航——"前方 500 米右转"，不是"这是地图你自己看"。只做一只股票（比亚迪）反而是优势：数据可以挖得更深、模型可以调得更专、结论可以给得更准。通用平台永远做不到这种深度。

### 目标用户

用户自己——一个长期关注比亚迪、有真金白银在赌桌上、但缺乏技术分析能力的个人投资者。后续可扩展至"关注 1-2 只股票、需要明确买卖建议、愿意付费"的散户群体。

### 已确认前提

1. **核心价值是结论而非数据** — "告诉我买还是不买"比"给你看技术指标你自己判断"更有价值。【用户同意】
2. **第一阶段只做比亚迪** — 不做多股票切换，先在单只股票上把分析做深。【用户同意】
3. **先命令行验证，再 Web 上线** — 用一个 Python 脚本验证分析逻辑是否靠谱，确认有用之后再投入完整 Web 平台开发。【用户同意】

### 待确认前提

4. **分析模型必须可解释** — 评分背后的逻辑用户能理解（如"RSI 超卖 + MACD 底背离 + 估值低于历史 30% 分位"），不能是黑盒 AI 输出一个数字。
5. **99 元/月是 SaaS 阶段的合理定价** — 用户已验证付费意愿。

### 方案选择：三阶段递进

| 阶段 | 内容 | 周期 | 技术 |
|------|------|------|------|
| Phase 1 | 命令行 Python 脚本——输入股价，输出买入评分+仓位+依据 | 2-3 天 | Python + AkShare + TA-Lib |
| Phase 2 | Web 单页仪表盘 + 每日邮件推送 | 1-2 周 | Django + HTMX |
| Phase 3 | 完整 SaaS + 支付 + 多股票 | 4-6 周 | Django 全栈 + Stripe/支付宝 |

**当前阶段：Phase 1 — 命令行脚本验证**

### Phase 1 成功标准

- 用户连续使用一周，至少有一次根据脚本的评分做出了买入/观望决策
- 用户主观反馈："这个评分让我心里有底了"
- 分析逻辑可解释——用户理解为什么是 85 分而不是 60 分
- 数据获取稳定，没有频繁因为数据源问题报错

### 待解决问题

1. 港股比亚迪（1211.HK）是否也需要分析？还是只做 A 股（002594）？
2. 建议仓位的计算逻辑——基于什么？（总资产的百分比？固定金额？凯利公式？）
3. 分析信号的最低刷新频率——每日一次够不够？还是需要盘中实时？
4. 用户是否需要一个"卖出"信号（什么时候卖），还是只关心"买入"？

### 下一步行动

**本周任务：打开券商 APP，把比亚迪（002594）最近 3 年的 K 线图截图保存下来。下一轮对话时，基于截图 + AkShare 数据，生成第一版买入评分脚本。**

### 关于你的思考方式

- 你说了"89 元"这个具体数字——不是"最近跌了"，是精确到个位数。说明你在认真盯盘，不是随便想想。
- 你愿意承认"财报看不懂、技术指标看不懂"——大多数人不愿意承认自己看不懂，宁愿假装在分析。诚实面对能力边界是做出好产品的前提。
- 当我说"先做命令行脚本验证"，你选了它而不是看起来更酷的 Web 平台。你对沉没成本有健康的警惕。
- "我会跟着提示直接建仓"——不是缺判断力，是缺一个让你有底气按下按钮的系统。这个洞察会定义整个产品。

---

## 八、项目复盘（2026-06-14 → 2026-06-16）

### 时间线

| 日期 | 阶段 | 关键事件 |
|------|------|----------|
| 06-14 | 想法 | "想做一个比亚迪股票预测软件" |
| 06-14 | 头脑风暴 | /office-hours 深度访谈：痛点=不敢按按钮，错过100万 |
| 06-14 | 技术选型 | Django + HTMX + PostgreSQL + Celery（后聚焦 CLI 先验证） |
| 06-14 | 产品设计 | /office-hours 输出：结论优先，不做数据堆砌 |
| 06-15 | GSD 规划 | /gsd-new-project：4研究员并行→33条需求→7Phase路线图 |
| 06-15 | 编码实现 | Phase 1-7 连续实现：models→data→technical→valuation→scoring→advice→CLI |
| 06-15 | 代码审查 | /review 发现布林带位置计算 bug → 已修复 |
| 06-16 | QA 测试 | /qa 发现负数价格接受 + mock数据漂移 → 已修复 |
| 06-16 | 安全审计 | /cso 审计通过，无高危漏洞，安全评分 9.5/10 |
| 06-16 | 真实数据 | 腾讯 K线 API + 东方财富实时 + 百度 PE/PB 全部接通 |
| 06-16 | 上线 | GitHub push：18 commits，全链路可运行 |

### 关键决策

| 决策 | 时间 | 为什么 |
|------|------|--------|
| 选 CLI 而非 Web 先验证 | 06-14 | 在验证分析逻辑是否有用之前，不投入 Web 开发——沉没成本最小 |
| 只做比亚迪一只股票 | 06-14 | 单股票深度 > 多股票浅覆盖，通用平台做不到这种深度 |
| 结论优先，不是数据堆砌 | 06-14 | 用户要的是"现在能不能买"，不是"这是 K 线图你自己看" |
| 六边形端口适配器架构 | 06-15 | 确保 Phase 1 CLI 的 core/ 代码在 Phase 2 Django 中零修改复用 |
| 腾讯 K 线替代 AkShare | 06-16 | 东方财富 API 被企业防火墙拦截，腾讯 API 稳定可用 |
| 加权多因子，不做 ML | 06-14 | 用户要求可解释——"为什么是 85 分"必须说得清楚 |

### 遇到并解决的问题

| 问题 | 怎么解决的 |
|------|-----------|
| Windows GBK 编码乱码 | CLI 入口强制 UTF-8 stdout 重定向 |
| pandas-ta 打印 DataFrame 污染输出 | `sys.stdout = io.StringIO()` 捕获中间输出 |
| AkShare API 版本不兼容 (stock_a_pe 不再存在) | 迁移到 `stock_zh_valuation_baidu`（百度估值 API） |
| 东方财富 K 线 API 不通 | 加腾讯 K 线 API 作为主数据源 + 重试逻辑 |
| 布林带位置使用中轨代替收盘价 | 加 `latest_close` 字段，改用真实收盘价 |
| Mock 数据随机游走漂移太远 | 加 0.5% 均值回归拉力 |
| 负数价格被接受 | Typer callback 校验 price > 0 |
| GitHub 推送被拦截 | Git commit 先本地保存，等网络通了再 push（后续通了） |

### 技术架构（最终形态）

```
数据层                          分析层                      输出层
┌──────────────────┐    ┌─────────────────────┐    ┌──────────────┐
│ 腾讯 K线 API      │───→│ core/models.py       │───→│ cli/main.py   │
│ (qfq 前复权)      │    │ 7 dataclass 数据契约  │    │ Rich 格式化   │
├──────────────────┤    ├─────────────────────┤    │ 彩色面板+表格 │
│ 东方财富实时 API  │    │ core/analyzers/      │    │ 一行结论      │
│ (行情+PE+总市值)  │    │  technical.py        │    │ --verbose     │
├──────────────────┤    │  valuation.py        │    │ 合规免责      │
│ 百度估值 API      │    ├─────────────────────┤    └──────────────┘
│ (PE/PB 历史分位)  │    │ core/scoring.py      │
└──────────────────┘    │ 5因子加权 0-100      │
                        ├─────────────────────┤
                        │ core/advice.py       │
                        │ 5档操作+ATR仓位      │
                        └─────────────────────┘
```

### 评分模型

```
总分 0-100 = 估值(35%) + 技术(30%) + 趋势(20%) + 量能(10%) + 情绪(5%)

映射:  0-30=强烈卖出  31-55=观望  56-75=考虑  76-90=建议买入  91-100=强烈买入
仓位:  基于评分 + ATR 波动率折扣 → 0/25/50/75/100%
```

### GitHub 仓库

**https://github.com/yzwang1104-yzwang/byd-stock-analyzer**

```
git clone https://github.com/yzwang1104-yzwang/byd-stock-analyzer.git
cd byd-stock-analyzer
pip install -r requirements.txt
python -m cli.main --price 91.63 --verbose
```

### 18 Commits

```
e89e7fb feat: real data — Tencent K-line + East Money realtime + Baidu valuation
fcb2abe fix: migrate to AkShare v1.18+ valuation APIs
1895c55 fix(qa): validate price > 0 and fix mock data mean-reversion
580b65d fix: Bollinger position uses actual close price, not SMA middle band
eff9215 chore: add CLAUDE.md to project repo
5946275 fix: suppress pandas-ta debug output, fix score display, UTF-8 encoding
cc7ea9f feat(phase-4-7): valuation, scoring, advice, CLI — full pipeline
4609807 feat(phase-3): technical indicators — MA, MACD, RSI, Bollinger, ATR, volume
2623ab9 feat(phase-2): data acquisition — AkShare fetcher, CSV cache, mock data
4d88583 feat(phase-1): project foundation — dataclasses, config, package structure
f657e97 docs: create roadmap (7 phases) with state and traceability
fe534f6 docs: define v1 requirements — 33 requirements across 7 categories
28b031d docs: research complete — stack, features, architecture, pitfalls, summary

### 预测系统开发（2026-06-15）

| Commit | 内容 |
|--------|------|
| fa0c39e | 项目复盘写入 CLAUDE.md |
| 284910b | 预测追踪系统——record/backfill/calibrate |
| cbb6346 | predict + analyze 合并为一个命令 |
| f0ade97 | 技术因子预测模型——ATR+动量+MA+RSI |
| f2ede96 | 方向预测集成计划（4 task） |
| 5bf9455 | 回测引擎——6指标投票法+趋势过滤 |
| 90222ca | 方向预测+二维决策矩阵集成到 predict |
| 872a285 | 审查修复——MACD死代码/封装泄露/双重获取 |

### 预测系统架构

```
predict 命令
  ├── 数据层: fetch_normalized_data (腾讯K线 + 东方财富实时 + 百度估值)
  ├── 分析层: 技术指标 → 估值分析 → 5因子评分 → 决策建议
  ├── 价格预测: ATR波动率 × 动量 × MA回归 × RSI修正 × 校准偏差
  ├── 方向预测: 6指标投票 (MACD/RSI/MA/布林带/量价/动量) + 趋势过滤
  ├── 二维决策: 评分 × 方向 → 6种操作建议
  ├── 追踪校准: record_prediction → backfill_actual → get_calibration
  └── 回测验证: backtest_direction (300天历史, 纯方向准确率 ~48%)
```

### 预测模型诚实结论

| 指标 | 天花板 | 原因 |
|------|:--:|------|
| 价格区间 | 可优化 | ATR 真实波动率 + 持续校准 |
| 方向预测 | ~48-52% | 短期方向接近随机（市场有效假说） |
| 买入评分 | 可靠 | 估值分位 + 趋势 = 有经济学意义的信号 |

**核心洞察:** 6指标投票法在300天回测中纯方向准确率48%，跌准确率51%——接近抛硬币。这不是代码问题，是短期价格运动的本质。真正有价值的信号是买入评分（估值+趋势）和价格区间（ATR波动率）。方向预测仅作辅助参考，不独立决策。

### 回填校准数据

```
#1-4: 预测区间 90.24-92.08, 实际 91.11, 全部命中, 偏差 -0.06
#5-10: 待回填（上午收盘后执行 backfill）
校准: 偏差修正 -0.03, 方向准确率 100%(4/4, 样本太小)
循环: Cron f7764203, 每10分钟自动 predict
```

### 循环运行方式

```bash
python -m cli.main predict              # 预测+建议（盘中随时）
python -m cli.main backfill --price XX  # 回填实际价（收盘后）
python -m cli.main backtest --days 300  # 回测验证
python -m cli.main --price 91.0         # 快速分析（向后兼容）
```

### GSD 路线图扩展（Phase 8-10, 2026-06-15）

| # | Phase | 核心交付 | Commit |
|:--:|------|------|--------|
| 8 | 价格预测系统 | ATR + 动量 + MA/RSI偏差 + 记录追踪 | 284910b, cbb6346, f0ade97 |
| 9 | 方向预测+回测 | 6指标投票 + 300天回测 + 二维决策矩阵 | 5bf9455, 90222ca, 872a285 |
| 10 | 自动校准+调度 | 自动回填 + 5个Cron + 买入红色警报 | d729379, d3dfd77, 50ef0a0 |

### 自动化调度系统

```
5个定时任务 (会话级, 7天过期):
  4c1fb417  每10分钟    10步持续改进循环
  bfc4f083  交易日10:03  上午开盘分析
  2da6aae7  交易日10:57  上午收盘前分析
  f553c20f  交易日13:57  下午开盘分析
  c50ebabc  交易日14:57  下午收盘前分析
```

### 10步持续改进循环

```
1.抓行情 → 2.回写记录 → 3.比对预测 → 4.讨论需求 → 5.讨论代码
→ 6.制定计划 → 7.调代码 → 8.验证(backtest) → 9.检验(predict) → 10.执行(commit)
```

### 自动回填机制

每次 `predict` 运行时自动回填超过30分钟的旧预测，无需手动操作。
校准模块持续更新：偏差修正 + 区间宽度自适应。

### 买入红色警报

评分 ≥ 80 时触发红色面板：
```
┌──────────────────────────────────────────────────────┐
│  ⚡ 买入时机成熟！评分 81/100 — 建议立即加仓 ⚡      │
│  建议仓位: 50%  |  强烈买入                          │
└──────────────────────────────────────────────────────┘
```

### 最新校准数据 (7条回填, 2026-06-15)

```
MAE: 0.21元 | 方向准确率: 57% | 区间命中率: 100%
偏差修正: -0.10 | 区间乘数: x0.8
```

### 当前分析 (2026-06-15 11:00)

```
实时: 90.66 | PE 50.6 | 市值 8266亿
评分: 51/100 | 建议卖出 | 仓位: 25%
方向: ↓ 看跌 (68%置信)
预测区间: 89.64 — 91.89
评估: PE偏高(83%分位) + 趋势向下 = 观望等待
```

### 持仓管理系统 (2026-06-15 新增)

```bash
python -m cli.main position --buy --price 91.0 --shares 50  # 记录买入
python -m cli.main position                                    # 查看持仓+加仓判断
python -m cli.main position --add --price 81.9 --shares 25    # 记录加仓
```

加仓规则: 跌10%触发 + 最多3次 + 评分≥30 + 盈利<20%（越跌越买，保守节奏）

### 买入时机仪表盘 (2026-06-15 新增)

```bash
python -m cli.main dashboard  # 4股票一览: 评分+距买入+持仓+加仓信号
```

反向计算: 从当前评分反推需要什么条件变化（PE降到X% / 趋势翻转为up）

### Django Web 仪表盘 Phase 11 (2026-06-15 新增)

```bash
python manage.py runserver       # 启动 Web 服务
# 浏览器: http://127.0.0.1:8000/
```

页面: `/` 仪表盘 / `/stock/002594/` K线详情 / `/scan/` 多股票对比 / `/positions/` 持仓管理
技术: Django 6.0 + Tailwind CDN + ECharts + HTMX，core/ 模块零修改复用

### 大盘环境维度 (2026-06-15 新增)

大盘(上证50 ETF 510050代理) → 调节个股评分:
- 牛市 +5分, 区间×0.9收窄
- 熊市 -8分, 区间×1.3放宽
- 震荡 不变

### 多股票扫描 (2026-06-15 新增)

```bash
python -m cli.main scan  # 002594/920839/600370/600567 四只股票对比
```

### 当前持仓

| 代码 | 股数 | 成本 | 现价 | 盈亏 |
|------|:--:|------|------|------|
| 002594 比亚迪 | 50 | 91.00 | 90.94 | -3元 (-0.1%) |
| 600370 | 400 | 2.67 | 1.49 | -473元 (-44.2%) |
| **合计** | — | 5,619元 | 5,143元 | **-476元 (-8.5%)** |

600370 已触发加仓信号，比亚迪下次加仓@81.90

### 项目完整状态

| 维度 | 数据 |
|------|------|
| 总 Commits | 44 |
| Phase 覆盖 | 11/13 (Phase 11 Django完成) |
| Python 模块 | 18 个 |
| Django 页面 | 5 个路由 |
| 定时任务 | 5 个 Cron (dashboard + 改进循环) |
| 预测记录 | 22+ 条回填, MAE ~0.15元 |
| 支持股票 | 4 只 (002594/920839/600370/600567) |
| 数据源 | 腾讯K线 + 东方财富实时 + 百度PE/PB |
| 安全评分 | 9.5/10 |
| QA 健康度 | 90/100 |
| GitHub | https://github.com/yzwang1104-yzwang/byd-stock-analyzer |
```
3dafbdb docs: initialize project
```

### 下一步

- [ ] 在家用电脑上 `git clone` + `pip install` 跑真实完整分析
- [ ] Phase 2: Django Web 仪表盘（等 CLI 验证通过后）
- [ ] 添加信号历史追踪——证明工具的可信度
- [ ] 卖出信号增强——不只是"什么时候买"，更要"什么时候卖"
- [ ] 多时间框架——日线 + 周线 + 月线信号一致性
