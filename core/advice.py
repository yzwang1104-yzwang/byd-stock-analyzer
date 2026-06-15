"""决策引擎——评分→操作建议+仓位+依据。

设计原则:
- 纯函数: ScoreResult → AdviceResult
- 仓位基于评分+波动率（ATR）调整
- 卖出信号单独触发（RSI>70 且 PE>80%分位）
"""

import logging
from datetime import date
from typing import Optional

from core.config import (
    POSITION_TIERS,
    SCORE_THRESHOLDS,
    SELL_PE_PERCENTILE,
    SELL_RSI_THRESHOLD,
    ScoringConfig,
)
from core.models import AdviceResult, AnalysisResult, ScoreResult

logger = logging.getLogger(__name__)


def generate(
    score_result: ScoreResult,
    analysis: AnalysisResult,
    stock_name: str = "比亚迪",
    config: Optional[ScoringConfig] = None,
    current_price: Optional[float] = None,
) -> AdviceResult:
    """生成最终操作建议。

    Args:
        score_result: 评分结果
        analysis: 原始分析数据（用于提取卖出信号和依据）
        stock_name: 股票名称
        config: 配置
        current_price: 用户输入的当前价格

    Returns:
        AdviceResult——面向用户的最终建议
    """
    if config is None:
        config = ScoringConfig()

    score = score_result.score

    # 1. 操作建议映射
    action, action_label = _score_to_action(score)

    # 2. 卖出信号覆盖（SELL-01）
    if analysis.rsi_14 is not None and analysis.pe_percentile is not None:
        if analysis.rsi_14 >= SELL_RSI_THRESHOLD and analysis.pe_percentile >= SELL_PE_PERCENTILE:
            action = "sell"
            action_label = "建议卖出"
            score = min(score, 40)  # 卖出信号限制最高分

    # 3. 仓位计算
    position_pct = _calc_position(score, analysis)

    # 4. 生成依据
    rationale = _generate_rationale(score_result, analysis, current_price)

    # 5. 详细指标（--verbose）
    details = _generate_details(score_result, analysis, current_price)

    return AdviceResult(
        stock_code=score_result.stock_code,
        stock_name=stock_name,
        advice_date=score_result.score_date or date.today(),
        score=score,
        action=action,
        action_label=action_label,
        position_pct=position_pct,
        rationale=rationale,
        confidence=score_result.confidence,
        details=details,
    )


def _score_to_action(score: int) -> tuple[str, str]:
    """评分 → 操作建议映射（SCOR-03）。"""
    if score <= SCORE_THRESHOLDS.strong_sell_max:
        return "strong_sell", "强烈卖出"
    elif score <= SCORE_THRESHOLDS.sell_max:
        return "sell", "建议卖出"
    elif score <= SCORE_THRESHOLDS.hold_max:
        return "hold", "观望等待"
    elif score <= SCORE_THRESHOLDS.buy_max:
        return "buy", "建议买入"
    else:
        return "strong_buy", "强烈买入"


def _calc_position(score: int, analysis: AnalysisResult) -> int:
    """计算建议仓位百分比（SCOR-04）。

    基于评分 + ATR 波动率调整——高波动降低仓位。
    """
    # 基础仓位（基于评分）
    if score >= 90:
        base = 100
    elif score >= 76:
        base = 75
    elif score >= 56:
        base = 50
    elif score >= 31:
        base = 25
    else:
        base = 0

    # ATR 波动率调整
    if analysis.atr_14 is not None and analysis.bollinger_middle is not None:
        vol_ratio = analysis.atr_14 / analysis.bollinger_middle if analysis.bollinger_middle > 0 else 0.02
        if vol_ratio > 0.04:  # 日均波动 >4% —— 高波动
            base = max(0, base - 25)
        elif vol_ratio > 0.03:
            base = max(0, base - 10)

    # 取最接近的合法档位
    return min(POSITION_TIERS, key=lambda x: abs(x - base))


def _generate_rationale(
    score_result: ScoreResult,
    analysis: AnalysisResult,
    current_price: Optional[float],
) -> str:
    """生成一句可解释依据（OUT-01）。"""
    parts = []

    # 估值
    if analysis.pe_percentile is not None:
        level = "低位" if analysis.pe_percentile < 30 else ("高位" if analysis.pe_percentile > 70 else "中位")
        parts.append(f"PE 处于历史{level}")
    if analysis.vs_industry_pe:
        parts.append(f"{analysis.vs_industry_pe}行业均值")

    # 技术面
    if analysis.rsi_14 is not None:
        if analysis.rsi_14 <= 30:
            parts.append("RSI 超卖")
        elif analysis.rsi_14 >= 70:
            parts.append("RSI 超买")

    if score_result.buy_signals:
        parts.append(score_result.buy_signals[0])
    if score_result.sell_signals:
        parts.append(score_result.sell_signals[0])

    if not parts:
        parts.append("指标综合评分")

    rationale = "；".join(parts[:3])  # 最多 3 个关键点
    if current_price:
        rationale = f"当前价 {current_price} 元，{rationale}"

    return rationale


def _generate_details(
    score_result: ScoreResult,
    analysis: AnalysisResult,
    current_price: Optional[float],
) -> list[str]:
    """生成详细指标列表（--verbose / OUT-03）。"""
    details = []
    bd = score_result.breakdown

    if current_price:
        details.append(f"当前价格: {current_price} 元")
    details.append(f"综合评分: {score_result.score}/100 ({score_result.confidence}置信度)")
    details.append("")
    details.append("=== 评分细项 ===")
    details.append(f"估值因子: {bd.valuation_score:.1f} / {bd.valuation_score / 0.35:.0f}分  (权重 35%)")
    details.append(f"技术因子: {bd.technical_score:.1f} / {bd.technical_score / 0.30:.0f}分  (权重 30%)")
    details.append(f"趋势因子: {bd.trend_score:.1f} / {bd.trend_score / 0.20:.0f}分  (权重 20%)")
    details.append(f"量能因子: {bd.volume_score:.1f} / {bd.volume_score / 0.10:.0f}分  (权重 10%)")
    details.append(f"情绪因子: {bd.sentiment_score:.1f} / {bd.sentiment_score / 0.05:.0f}分  (权重 5%)")
    details.append("")
    details.append("=== 技术指标 ===")
    if analysis.ma_20:
        details.append(f"MA20:  {analysis.ma_20}  |  MA50: {analysis.ma_50 or 'N/A'}  |  MA200: {analysis.ma_200 or 'N/A'}")
    if analysis.rsi_14:
        details.append(f"RSI(14): {analysis.rsi_14}  {'(超卖)' if analysis.rsi_14 <= 30 else '(超买)' if analysis.rsi_14 >= 70 else ''}")
    if analysis.macd is not None:
        details.append(f"MACD: {analysis.macd:.3f}  |  Signal: {analysis.macd_signal:.3f}  |  Hist: {analysis.macd_histogram:.3f}")
    if analysis.bollinger_middle:
        details.append(f"布林带: U={analysis.bollinger_upper}  M={analysis.bollinger_middle}  L={analysis.bollinger_lower}")
    if analysis.atr_14:
        details.append(f"ATR(14): {analysis.atr_14}  (日均波幅约 {analysis.atr_14 / analysis.bollinger_middle * 100:.1f}%)" if analysis.bollinger_middle else f"ATR(14): {analysis.atr_14}")
    details.append("")
    details.append("=== 估值 ===")
    details.append(f"PE 分位: {analysis.pe_percentile or 'N/A'}%  |  PB 分位: {analysis.pb_percentile or 'N/A'}%")
    if analysis.vs_industry_pe:
        details.append(f"vs 行业PE: {analysis.vs_industry_pe}")
    details.append("")
    details.append("=== 信号 ===")
    if score_result.buy_signals:
        details.append("买入信号: " + ", ".join(score_result.buy_signals))
    if score_result.sell_signals:
        details.append("卖出信号: " + ", ".join(score_result.sell_signals))
    if not score_result.buy_signals and not score_result.sell_signals:
        details.append("无明显买入/卖出信号")

    return details
