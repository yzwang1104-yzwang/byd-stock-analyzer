"""评分引擎——加权多因子综合评分 0-100。

设计原则:
- 纯函数: AnalysisResult → ScoreResult
- 权重可配置（从 ScoringConfig 读取）
- 看跌因子必须能压制买入评分（PITFALLS #6 防范确认偏差）
"""

import logging
from datetime import date
from typing import Optional

from core.config import (
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    SELL_PE_PERCENTILE,
    ScoringConfig,
)
from core.models import AnalysisResult, ScoreBreakdown, ScoreResult

logger = logging.getLogger(__name__)


def compute(result: AnalysisResult, config: Optional[ScoringConfig] = None) -> ScoreResult:
    """计算综合买入评分。

    Args:
        result: 技术和估值分析结果
        config: 评分配置（None = 使用默认配置）

    Returns:
        ScoreResult 包含 0-100 整数评分和细项
    """
    if config is None:
        config = ScoringConfig()

    breakdown = ScoreBreakdown()

    # 1. 估值因子 (35%)——PE/PB 分位越低越好
    breakdown.valuation_score = _score_valuation(result) * config.weights["valuation"]

    # 2. 技术因子 (30%)——RSI + MACD + 布林带
    breakdown.technical_score = _score_technical(result) * config.weights["technical"]

    # 3. 趋势因子 (20%)——均线结构
    breakdown.trend_score = _score_trend(result) * config.weights["trend"]

    # 4. 量能因子 (10%)——成交量确认
    breakdown.volume_score = _score_volume(result) * config.weights["volume"]

    # 5. 情绪因子 (5%)——当前未独立计算，用警告信号替代
    breakdown.sentiment_score = _score_sentiment(result) * config.weights["sentiment"]

    raw_total = breakdown.total
    score = min(100, max(0, round(raw_total)))

    # 置信度评估
    confidence = _assess_confidence(result)

    # 信号收集
    buy_signals = _collect_buy_signals(result)
    sell_signals = _collect_sell_signals(result)

    return ScoreResult(
        stock_code=result.stock_code,
        score_date=result.analysis_date,
        score=score,
        confidence=confidence,
        breakdown=breakdown,
        buy_signals=buy_signals,
        sell_signals=sell_signals,
    )


def _score_valuation(result: AnalysisResult) -> float:
    """估值评分: PE 分位越低分数越高，0-100 映射。"""
    if result.pe_percentile is None and result.pb_percentile is None:
        return 50.0  # 数据不可用时中性

    pe_score = 0.0
    pb_score = 0.0
    count = 0

    if result.pe_percentile is not None:
        # 分位 0→100, PE 低=分位低=好, 所以 100-分位
        pe_score = 100.0 - result.pe_percentile
        count += 1

    if result.pb_percentile is not None:
        pb_score = 100.0 - result.pb_percentile
        count += 1

    return (pe_score + pb_score) / count if count > 0 else 50.0


def _score_technical(result: AnalysisResult) -> float:
    """技术评分: RSI + MACD + 布林带综合。"""
    score = 50.0  # 基准中性
    signals = 0

    # RSI: 超卖=好(买入机会), 超买=差
    if result.rsi_14 is not None:
        if result.rsi_14 <= RSI_OVERSOLD:
            score += 25  # 超卖 → 买入机会
        elif result.rsi_14 >= RSI_OVERBOUGHT:
            score -= 25  # 超买 → 谨慎
        elif result.rsi_14 < 50:
            score += 10  # 偏弱 → 可能有买入机会
        signals += 1

    # MACD: 柱状图为正=向好
    if result.macd_histogram is not None:
        if result.macd_histogram > 0:
            score += 10
        else:
            score -= 10
        signals += 1

    # 布林带: 接近下轨=超卖
    if result.bollinger_lower is not None and result.bollinger_middle is not None:
        close = result.bollinger_middle  # 用中轨近似
        band_width = result.bollinger_upper - result.bollinger_lower if result.bollinger_upper else 1
        if band_width > 0:
            position = (close - result.bollinger_lower) / band_width
            if position < 0.2:
                score += 15  # 接近下轨
            elif position > 0.8:
                score -= 15  # 接近上轨
        signals += 1

    return max(0, min(100, score))


def _score_trend(result: AnalysisResult) -> float:
    """趋势评分: 均线形态。"""
    trend_map = {
        "up": 85.0,
        "sideways_up": 65.0,
        "sideways": 50.0,
        "sideways_down": 35.0,
        "down": 15.0,
        "unknown": 50.0,
    }
    return trend_map.get(result.trend, 50.0)


def _score_volume(result: AnalysisResult) -> float:
    """量能评分: 量价配合判断。"""
    score = 50.0

    if result.volume_sma_20 is not None and result.atr_14 is not None:
        # 成交量无极端缩量 -> 中性偏正
        score = 55.0

    # 检查警告中的量能信号
    for w in result.warnings:
        if "成交量显著放大" in w:
            score += 15
        elif "成交量显著萎缩" in w:
            score -= 15

    return max(0, min(100, score))


def _score_sentiment(result: AnalysisResult) -> float:
    """情绪因子: 用警告信号数量作为代理。"""
    buy_count = sum(1 for w in result.warnings if any(
        kw in w for kw in ["金叉", "超卖", "下轨", "向好"]
    ))
    sell_count = sum(1 for w in result.warnings if any(
        kw in w for kw in ["死叉", "超买", "上轨"]
    ))

    if buy_count > sell_count:
        return 60.0
    elif sell_count > buy_count:
        return 40.0
    return 50.0


def _assess_confidence(result: AnalysisResult) -> str:
    """评估评分置信度。"""
    if result.is_degraded:
        return "低"

    # 检查指标覆盖度
    indicators_present = sum(1 for x in [
        result.rsi_14, result.macd, result.pe_percentile,
        result.bollinger_middle, result.atr_14,
    ] if x is not None)

    if indicators_present >= 4:
        return "高"
    elif indicators_present >= 2:
        return "中"
    return "低"


def _collect_buy_signals(result: AnalysisResult) -> list[str]:
    """收集买入信号。"""
    signals = []
    for w in result.warnings:
        if any(kw in w for kw in ["金叉", "超卖", "下轨", "向好"]):
            signals.append(w)
    if result.trend in ("up", "sideways_up"):
        signals.append(f"趋势向好: {result.trend}")
    if result.pe_percentile is not None and result.pe_percentile < 30:
        signals.append(f"PE 处于历史低位 ({result.pe_percentile:.0f}分位)")
    return signals


def _collect_sell_signals(result: AnalysisResult) -> list[str]:
    """收集卖出信号。"""
    signals = []
    for w in result.warnings:
        if any(kw in w for kw in ["死叉", "超买", "上轨"]):
            signals.append(w)
    if result.trend in ("down", "sideways_down"):
        signals.append(f"趋势走弱: {result.trend}")
    if result.pe_percentile is not None and result.pe_percentile > SELL_PE_PERCENTILE:
        signals.append(f"PE 处于历史高位 ({result.pe_percentile:.0f}分位)")
    return signals
