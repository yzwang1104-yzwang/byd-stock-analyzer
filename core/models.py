"""共享数据结构——所有 Phase 复用的数据契约。

设计原则:
- 纯 Python dataclass，零框架依赖
- 所有价格字段为 float，所有日期字段为 date
- 归一化发生在数据层边界，下游模块不接受原始 DataFrame
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class PriceBar:
    """单日 OHLCV 数据条（前复权）。"""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class NormalizedData:
    """归一化后的股票数据——跨模块边界的标准载体。

    从 AkShare DataFrame 转换而来，列名不再依赖中文。
    """

    stock_code: str
    stock_name: str
    prices: list[PriceBar]  # 按日期升序排列
    data_date: date  # 数据最新日期
    is_cached: bool = False
    cache_timestamp: Optional[str] = None

    @property
    def closes(self) -> list[float]:
        return [p.close for p in self.prices]

    @property
    def volumes(self) -> list[int]:
        return [p.volume for p in self.prices]

    @property
    def highs(self) -> list[float]:
        return [p.high for p in self.prices]

    @property
    def lows(self) -> list[float]:
        return [p.low for p in self.prices]

    @property
    def latest_price(self) -> float:
        return self.prices[-1].close if self.prices else 0.0

    @property
    def trading_days(self) -> int:
        return len(self.prices)


@dataclass
class ValuationData:
    """估值数据——PE/PB 历史和行业对比。"""

    stock_code: str
    current_pe: Optional[float] = None
    current_pb: Optional[float] = None
    pe_percentile: Optional[float] = None  # 0-100, 历史分位
    pb_percentile: Optional[float] = None
    industry_pe: Optional[float] = None
    industry_pb: Optional[float] = None
    pe_history: list[float] = field(default_factory=list)
    pb_history: list[float] = field(default_factory=list)
    data_date: Optional[date] = None

    @property
    def pe_level(self) -> str:
        """相对估值判断。"""
        if self.pe_percentile is None:
            return "未知"
        if self.pe_percentile <= 30:
            return "低估"
        elif self.pe_percentile <= 70:
            return "合理"
        else:
            return "高估"

    @property
    def pb_level(self) -> str:
        if self.pb_percentile is None:
            return "未知"
        if self.pb_percentile <= 30:
            return "低估"
        elif self.pb_percentile <= 70:
            return "合理"
        else:
            return "高估"


@dataclass
class IndicatorResult:
    """单个技术指标的计算结果。"""

    name: str
    value: float
    signal: str = ""  # "bullish", "bearish", "neutral"
    detail: str = ""  # 人类可读解释


@dataclass
class AnalysisResult:
    """技术分析模块的综合输出。

    由 TechnicalAnalyzer / ValuationAnalyzer 产出，
    被 ScoringEngine 消费。纯数据结构，无逻辑。
    """

    stock_code: str
    analysis_date: date

    # 技术指标
    ma_20: Optional[float] = None
    ma_50: Optional[float] = None
    ma_200: Optional[float] = None
    rsi_14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    bollinger_upper: Optional[float] = None
    bollinger_middle: Optional[float] = None
    bollinger_lower: Optional[float] = None
    atr_14: Optional[float] = None
    volume_sma_20: Optional[float] = None

    # 估值
    pe_percentile: Optional[float] = None
    pb_percentile: Optional[float] = None
    vs_industry_pe: Optional[str] = None  # "低于"/"高于"/"持平"
    vs_industry_pb: Optional[str] = None

    # 趋势判断
    trend: str = "neutral"  # "up", "down", "sideways"

    # 当前价格
    latest_close: Optional[float] = None

    # 元数据
    data_quality: str = "full"  # "full", "degraded", "partial"
    warnings: list[str] = field(default_factory=list)

    @property
    def is_degraded(self) -> bool:
        return self.data_quality != "full"


@dataclass
class ScoreBreakdown:
    """评分细项——展示每个因子的贡献。"""

    valuation_score: float = 0.0
    technical_score: float = 0.0
    trend_score: float = 0.0
    volume_score: float = 0.0
    sentiment_score: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.valuation_score
            + self.technical_score
            + self.trend_score
            + self.volume_score
            + self.sentiment_score
        )


@dataclass
class ScoreResult:
    """评分引擎输出。

    由 ScoringEngine.compute() 产出，被 AdviceEngine 消费。
    """

    stock_code: str
    score_date: date
    score: int  # 0-100 整数
    confidence: str = "中"  # "高" / "中" / "低"
    breakdown: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    buy_signals: list[str] = field(default_factory=list)  # 买入信号列表
    sell_signals: list[str] = field(default_factory=list)  # 卖出信号列表
    cooldown_active: bool = False


@dataclass
class AdviceResult:
    """最终建议——面向用户的输出。

    由 AdviceEngine.generate() 产出，被 CLI/Web 输出层消费。
    """

    stock_code: str
    stock_name: str
    advice_date: date
    score: int
    action: str  # "strong_buy" / "buy" / "hold" / "sell" / "strong_sell"
    action_label: str  # "强烈买入" / "建议买入" / "观望等待" / "建议卖出" / "强烈卖出"
    position_pct: int  # 0, 25, 50, 75, 100
    rationale: str  # 一句可解释依据
    confidence: str = "中"
    details: list[str] = field(default_factory=list)  # 展开的详细指标
    disclaimer: str = "分析结果仅供参考，不构成任何投资建议。投资有风险，入市需谨慎。"
