"""估值分析——PE/PB 历史分位 + 行业对比。

设计原则:
- 纯计算，无副作用
- 在数据不可用时优雅降级（VALU-04）
- scipy.stats.percentileofscore 用于分位计算
"""

import logging
from typing import Optional

from core.models import AnalysisResult, ValuationData

logger = logging.getLogger(__name__)


def analyze(result: AnalysisResult, valuation: Optional[ValuationData]) -> AnalysisResult:
    """在 AnalysisResult 上填充估值维度。

    Args:
        result: 已有技术指标的分析结果（原地修改）
        valuation: 估值数据（可为 None 表示数据不可用）

    Returns:
        更新后的 AnalysisResult
    """
    if valuation is None:
        result.warnings.append("估值数据不可用——评分将不包含估值维度")
        result.data_quality = "degraded"
        return result

    # PE 分位
    if valuation.pe_history and valuation.current_pe is not None:
        try:
            from scipy import stats
            result.pe_percentile = round(
                float(stats.percentileofscore(valuation.pe_history, valuation.current_pe)), 2
            )
        except Exception as e:
            logger.warning(f"PE 分位计算失败: {e}")

    # PB 分位
    if valuation.pb_history and valuation.current_pb is not None:
        try:
            from scipy import stats
            result.pb_percentile = round(
                float(stats.percentileofscore(valuation.pb_history, valuation.current_pb)), 2
            )
        except Exception as e:
            logger.warning(f"PB 分位计算失败: {e}")

    # 行业对比
    if valuation.industry_pe is not None and valuation.current_pe is not None:
        if valuation.current_pe < valuation.industry_pe:
            result.vs_industry_pe = "低于"
        elif valuation.current_pe > valuation.industry_pe:
            result.vs_industry_pe = "高于"
        else:
            result.vs_industry_pe = "持平"

    if valuation.industry_pb is not None and valuation.current_pb is not None:
        if valuation.current_pb < valuation.industry_pb:
            result.vs_industry_pb = "低于"
        elif valuation.current_pb > valuation.industry_pb:
            result.vs_industry_pb = "高于"
        else:
            result.vs_industry_pb = "持平"

    return result
