"""scoring.py + advice.py 单元测试 — 核心评分和决策算法。"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from core.models import (
    AnalysisResult,
    ScoreBreakdown,
    ScoreResult,
    AdviceResult,
)
from core.config import ScoringConfig


# ====== Fixtures ======

@pytest.fixture
def base_analysis() -> AnalysisResult:
    """构造一个基础 AnalysisResult，各项指标非空。"""
    return AnalysisResult(
        stock_code="002594",
        analysis_date=date.today(),
        latest_close=90.0,
        rsi_14=40.0,
        macd=-0.5,
        macd_signal=-0.8,
        macd_histogram=0.3,
        bollinger_upper=100.0,
        bollinger_middle=90.0,
        bollinger_lower=80.0,
        ma_20=88.0,
        ma_50=92.0,
        ma_200=95.0,
        atr_14=3.0,
        volume_sma_20=5000000,
        pe_percentile=25.0,
        pb_percentile=30.0,
        trend="sideways",
        data_quality="full",
        warnings=[],
    )


@pytest.fixture
def scoring_config() -> ScoringConfig:
    return ScoringConfig()


# ====== Scoring 单元测试 ======

class TestScoreValuation:
    """估值评分：PE/PB 分位越低分数越高。"""

    def test_low_pe_gives_high_score(self):
        from core.scoring import _score_valuation

        result = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            pe_percentile=5.0, pb_percentile=None,
        )
        score = _score_valuation(result)
        assert score == 95.0  # 100 - 5

    def test_mixed_pe_pb_averages(self):
        from core.scoring import _score_valuation

        result = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            pe_percentile=20.0, pb_percentile=60.0,
        )
        score = _score_valuation(result)
        # PE: 80, PB: 40, avg = 60
        assert score == 60.0

    def test_no_data_returns_neutral(self):
        from core.scoring import _score_valuation

        result = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            pe_percentile=None, pb_percentile=None,
        )
        score = _score_valuation(result)
        assert score == 50.0

    def test_high_pe_gives_low_score(self):
        from core.scoring import _score_valuation

        result = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            pe_percentile=90.0, pb_percentile=None,
        )
        score = _score_valuation(result)
        assert score == 10.0  # 100 - 90


class TestScoreTechnical:
    """技术评分：RSI + MACD + 布林带。"""

    def test_oversold_rsi_adds_25(self, base_analysis):
        from core.scoring import _score_technical

        base_analysis.rsi_14 = 25.0  # ≤ RSI_OVERSOLD (30)
        base_analysis.macd_histogram = None
        base_analysis.bollinger_lower = None
        score = _score_technical(base_analysis)
        assert score > 50  # RSI 超卖加分

    def test_overbought_rsi_subtracts_25(self, base_analysis):
        from core.scoring import _score_technical

        base_analysis.rsi_14 = 75.0  # ≥ RSI_OVERBOUGHT (70)
        base_analysis.macd_histogram = None
        base_analysis.bollinger_lower = None
        score = _score_technical(base_analysis)
        assert score < 50  # RSI 超买减分

    def test_positive_macd_adds_score(self, base_analysis):
        from core.scoring import _score_technical

        base_analysis.rsi_14 = None
        base_analysis.macd_histogram = 1.5
        base_analysis.bollinger_lower = None
        score = _score_technical(base_analysis)
        assert score == 60  # 50 + 10 for positive MACD

    def test_near_lower_band_adds_score(self, base_analysis):
        from core.scoring import _score_technical

        base_analysis.rsi_14 = None
        base_analysis.macd_histogram = None
        base_analysis.latest_close = 82.0  # near lower band (80)
        # position = (82-80)/(100-80) = 2/20 = 0.1 (< 0.2)
        score = _score_technical(base_analysis)
        assert score == 65  # 50 + 15 for near lower band

    def test_score_clamped_0_to_100(self, base_analysis):
        from core.scoring import _score_technical

        base_analysis.rsi_14 = 10.0
        base_analysis.macd_histogram = 10.0
        base_analysis.latest_close = 81.0
        score = _score_technical(base_analysis)
        assert 0 <= score <= 100


class TestScoreTrend:
    """趋势评分：均线形态映射。"""

    def test_up_trend_high_score(self):
        from core.scoring import _score_trend

        result = AnalysisResult(stock_code="002594", analysis_date=date.today(), trend="up")
        assert _score_trend(result) == 85.0

    def test_down_trend_low_score(self):
        from core.scoring import _score_trend

        result = AnalysisResult(stock_code="002594", analysis_date=date.today(), trend="down")
        assert _score_trend(result) == 15.0

    def test_unknown_trend_neutral(self):
        from core.scoring import _score_trend

        result = AnalysisResult(stock_code="002594", analysis_date=date.today(), trend="unknown")
        assert _score_trend(result) == 50.0


class TestScoreVolume:
    """量能评分：成交量确认。"""

    def test_volume_spike_adds_score(self):
        from core.scoring import _score_volume

        result = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            volume_sma_20=5000000, atr_14=3.0,
            warnings=["成交量显著放大"],
        )
        score = _score_volume(result)
        assert score == 70  # 55 + 15

    def test_volume_shrink_subtracts(self):
        from core.scoring import _score_volume

        result = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            volume_sma_20=5000000, atr_14=3.0,
            warnings=["成交量显著萎缩"],
        )
        score = _score_volume(result)
        assert score == 40  # 55 - 15


class TestScoreSentiment:
    """情绪因子：警告信号代理。"""

    def test_more_buy_signals(self):
        from core.scoring import _score_sentiment

        result = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            warnings=["RSI超卖", "MACD金叉"],
        )
        assert _score_sentiment(result) == 60.0

    def test_more_sell_signals(self):
        from core.scoring import _score_sentiment

        result = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            warnings=["RSI超买", "死叉"],
        )
        assert _score_sentiment(result) == 40.0


class TestAssessConfidence:
    """置信度评估。"""

    def test_degraded_data_low_confidence(self):
        from core.scoring import _assess_confidence

        result = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            data_quality="degraded",
        )
        assert _assess_confidence(result) == "低"

    def test_full_indicators_high_confidence(self, base_analysis):
        from core.scoring import _assess_confidence

        assert _assess_confidence(base_analysis) == "高"  # 5 indicators present


class TestCollectSignals:
    """信号收集。"""

    def test_buy_signals_from_warnings(self):
        from core.scoring import _collect_buy_signals

        result = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            trend="up", pe_percentile=20.0, pb_percentile=15.0,
            warnings=["MACD金叉", "RSI超卖"],
        )
        signals = _collect_buy_signals(result)
        assert any("金叉" in s for s in signals)
        assert any("PE" in s for s in signals)

    def test_sell_signals_from_trend(self):
        from core.scoring import _collect_sell_signals

        result = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            trend="down", pe_percentile=85.0,
            warnings=["MACD死叉"],
        )
        signals = _collect_sell_signals(result)
        assert any("走弱" in s for s in signals)
        assert any("高位" in s for s in signals)


class TestComputeEndToEnd:
    """端到端评分计算。"""

    def test_full_compute_returns_valid_score(self, base_analysis, scoring_config):
        from core.scoring import compute

        result = compute(base_analysis, scoring_config)
        assert isinstance(result, ScoreResult)
        assert 0 <= result.score <= 100
        assert result.stock_code == "002594"
        assert result.confidence in ("高", "中", "低")

    def test_bullish_scenario_high_score(self, scoring_config):
        from core.scoring import compute

        analysis = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            latest_close=80.0,
            rsi_14=25.0,           # 超卖
            macd_histogram=2.0,     # 金叉
            bollinger_upper=100.0, bollinger_middle=85.0, bollinger_lower=70.0,
            pe_percentile=10.0,     # 极低
            pb_percentile=5.0,      # 极低
            trend="up",             # 上升趋势
            volume_sma_20=5000000, atr_14=3.0,
            data_quality="full",
            warnings=["MACD金叉"],
        )
        result = compute(analysis, scoring_config)
        # 极低PE + 超卖RSI + 上升趋势 → 应该很高
        assert result.score >= 70

    def test_bearish_scenario_low_score(self, scoring_config):
        from core.scoring import compute

        analysis = AnalysisResult(
            stock_code="002594", analysis_date=date.today(),
            latest_close=120.0,
            rsi_14=80.0,           # 超买
            macd_histogram=-3.0,    # 死叉
            bollinger_upper=130.0, bollinger_middle=110.0, bollinger_lower=90.0,
            pe_percentile=90.0,     # 极贵
            pb_percentile=85.0,     # 贵
            trend="down",           # 下跌
            volume_sma_20=5000000, atr_14=3.0,
            data_quality="full",
            warnings=["MACD死叉", "RSI超买"],
        )
        result = compute(analysis, scoring_config)
        # 极贵PE + 超买RSI + 下跌趋势 → 应该很低
        assert result.score <= 40


# ====== Advice 单元测试 ======

class TestScoreToAction:
    """评分 → 操作建议映射（红线 #11：核心逻辑必须有测试）。"""

    def _call(self, score: int) -> tuple:
        from core.advice import _score_to_action
        return _score_to_action(score)

    def test_strong_buy(self):
        action, label = self._call(95)
        assert action == "strong_buy"
        assert "强烈买入" in label

    def test_buy(self):
        action, label = self._call(80)
        assert action == "buy"
        assert "建议买入" in label

    def test_hold(self):
        action, label = self._call(60)
        assert action == "hold"
        assert "观望" in label

    def test_sell(self):
        action, label = self._call(35)
        assert action == "sell"
        assert "建议卖出" in label

    def test_strong_sell(self):
        action, label = self._call(10)
        assert action == "strong_sell"
        assert "强烈卖出" in label


class TestGenerateAdvice:
    """端到端建议生成。"""

    def test_buy_advice_with_low_score(self, base_analysis, scoring_config):
        from core.scoring import compute
        from core.advice import generate

        base_analysis.pe_percentile = 95.0
        base_analysis.trend = "down"
        score_result = compute(base_analysis, scoring_config)
        advice = generate(score_result, base_analysis, stock_name="比亚迪")

        assert isinstance(advice, AdviceResult)
        assert advice.stock_name == "比亚迪"
        assert advice.score == score_result.score
        assert advice.position_pct in (0, 25, 50, 75, 100)
        assert "投资有风险" in advice.disclaimer

    def test_position_pct_proportional_to_score(self, base_analysis, scoring_config):
        from core.scoring import compute
        from core.advice import generate

        # 高分 → 高仓位
        base_analysis.pe_percentile = 5.0
        base_analysis.trend = "up"
        base_analysis.rsi_14 = 25.0
        high_score = compute(base_analysis, scoring_config)
        high_advice = generate(high_score, base_analysis)

        # 低分 → 低仓位
        base_analysis.pe_percentile = 95.0
        base_analysis.trend = "down"
        base_analysis.rsi_14 = 80.0
        low_score = compute(base_analysis, scoring_config)
        low_advice = generate(low_score, base_analysis)

        assert high_advice.position_pct >= low_advice.position_pct
