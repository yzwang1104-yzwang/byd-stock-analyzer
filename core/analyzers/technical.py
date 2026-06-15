"""技术指标分析——MA, MACD, RSI, 布林带, ATR, 成交量。

设计原则:
- NormalizedData 输入 → AnalysisResult 输出（纯函数，无副作用）
- 所有指标使用 shift(1) 防止前瞻偏差
- pandas-ta 作为主计算引擎，无 TA-Lib 硬依赖
"""

import logging
from datetime import date

import numpy as np
import pandas as pd

# 抑制 DataFrame 打印
pd.set_option("display.max_rows", 0)
pd.set_option("display.max_columns", 0)

from core.config import (
    ATR_PERIOD,
    BOLLINGER_PARAMS,
    MACD_PARAMS,
    MA_PERIODS,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_PERIOD,
    VOLUME_SMA_PERIOD,
)
from core.models import AnalysisResult, NormalizedData

logger = logging.getLogger(__name__)


def analyze(data: NormalizedData) -> AnalysisResult:
    """从归一化数据计算所有技术指标。

    Args:
        data: 归一化股票数据

    Returns:
        AnalysisResult 包含全部技术指标和技术部分信号
    """
    if not data.prices:
        return AnalysisResult(
            stock_code=data.stock_code,
            analysis_date=data.data_date,
            data_quality="degraded",
            warnings=["无价格数据"],
        )

    result = AnalysisResult(
        stock_code=data.stock_code,
        analysis_date=data.data_date,
    )

    df = _prices_to_dataframe(data)
    if df.empty:
        result.data_quality = "degraded"
        result.warnings.append("无法转换为 DataFrame")
        return result

    # 关键：shift(1) 防止前瞻偏差——T 日的信号不使用 T 日的数据
    df_safe = df.shift(1)

    try:
        # 1. 移动均线
        _compute_ma(result, df_safe)

        # 2. MACD
        _compute_macd(result, df_safe)

        # 3. RSI
        _compute_rsi(result, df_safe)

        # 4. 布林带
        _compute_bollinger(result, df_safe)

        # 5. ATR
        _compute_atr(result, df_safe)

        # 6. 成交量均线
        _compute_volume(result, df_safe)

        # 7. 趋势判断
        _compute_trend(result, df_safe)

    except Exception as e:
        logger.error(f"指标计算失败: {e}")
        result.warnings.append(f"指标计算异常: {e}")
        result.data_quality = "degraded"

    return result


def _prices_to_dataframe(data: NormalizedData) -> pd.DataFrame:
    """PriceBar 列表 → pandas DataFrame（OHLCV 列）。"""
    records = [
        {
            "date": p.date,
            "open": p.open,
            "high": p.high,
            "low": p.low,
            "close": p.close,
            "volume": p.volume,
        }
        for p in data.prices
    ]
    df = pd.DataFrame(records)
    df.set_index("date", inplace=True)
    return df


def _compute_ma(result: AnalysisResult, df: pd.DataFrame) -> None:
    """计算移动均线。"""
    for period in MA_PERIODS:
        sma = df["close"].rolling(window=period).mean()
        latest = sma.iloc[-1] if not sma.empty else None
        if latest is not None and not np.isnan(latest):
            setattr(result, f"ma_{period}", round(float(latest), 2))

    # 金叉/死叉判断（MA20 vs MA50）
    if result.ma_20 and result.ma_50:
        if result.ma_20 > result.ma_50:
            result.warnings.append("MA20 在 MA50 上方，短期趋势向好")


def _compute_macd(result: AnalysisResult, df: pd.DataFrame) -> None:
    """计算 MACD 并检测金叉/死叉。"""
    import pandas_ta as ta

    try:
        macd_df = df.ta.macd(
            fast=MACD_PARAMS["fast"],
            slow=MACD_PARAMS["slow"],
            signal=MACD_PARAMS["signal"],
            append=False,
        )
        # pandas-ta 返回: MACD_12_26_9, MACDs_12_26_9, MACDh_12_26_9
        if macd_df is not None and not macd_df.empty:
            col_macd = [c for c in macd_df.columns if c.startswith("MACD_") and not c.endswith("s_") and not c.endswith("h_")][0]
            col_signal = [c for c in macd_df.columns if c.startswith("MACDs_")][0]
            col_hist = [c for c in macd_df.columns if c.startswith("MACDh_")][0]

            result.macd = round(float(macd_df[col_macd].iloc[-1]), 4)
            result.macd_signal = round(float(macd_df[col_signal].iloc[-1]), 4)
            result.macd_histogram = round(float(macd_df[col_hist].iloc[-1]), 4)

            # 金叉/死叉检测
            if len(macd_df) >= 2:
                prev_macd = macd_df[col_macd].iloc[-2]
                prev_signal = macd_df[col_signal].iloc[-2]
                curr_macd = macd_df[col_macd].iloc[-1]
                curr_signal = macd_df[col_signal].iloc[-1]

                if prev_macd <= prev_signal and curr_macd > curr_signal:
                    result.warnings.append("MACD 金叉信号")
                elif prev_macd >= prev_signal and curr_macd < curr_signal:
                    result.warnings.append("MACD 死叉信号")
    except Exception as e:
        logger.warning(f"MACD 计算失败: {e}")


def _compute_rsi(result: AnalysisResult, df: pd.DataFrame) -> None:
    """计算 RSI(14) 并判断超买超卖。"""
    import pandas_ta as ta

    try:
        rsi = df.ta.rsi(length=RSI_PERIOD, append=False)
        if rsi is not None and not rsi.empty:
            result.rsi_14 = round(float(rsi.iloc[-1]), 2)

            if result.rsi_14 <= RSI_OVERSOLD:
                result.warnings.append(f"RSI 超卖 ({result.rsi_14})")
            elif result.rsi_14 >= RSI_OVERBOUGHT:
                result.warnings.append(f"RSI 超买 ({result.rsi_14})")
    except Exception as e:
        logger.warning(f"RSI 计算失败: {e}")


def _compute_bollinger(result: AnalysisResult, df: pd.DataFrame) -> None:
    """计算布林带(20,2)。"""
    import pandas_ta as ta

    try:
        bb = df.ta.bbands(
            length=BOLLINGER_PARAMS["period"],
            std=BOLLINGER_PARAMS["std_dev"],
            append=False,
        )
        if bb is not None and not bb.empty:
            col_upper = [c for c in bb.columns if c.startswith("BBU_")][0]
            col_mid = [c for c in bb.columns if c.startswith("BBM_")][0]
            col_lower = [c for c in bb.columns if c.startswith("BBL_")][0]

            result.bollinger_upper = round(float(bb[col_upper].iloc[-1]), 2)
            result.bollinger_middle = round(float(bb[col_mid].iloc[-1]), 2)
            result.bollinger_lower = round(float(bb[col_lower].iloc[-1]), 2)

            # 价格位置判断
            close = df["close"].iloc[-1]
            if close <= result.bollinger_lower:
                result.warnings.append("价格触及布林带下轨——可能超卖")
            elif close >= result.bollinger_upper:
                result.warnings.append("价格触及布林带上轨——可能超买")
    except Exception as e:
        logger.warning(f"布林带计算失败: {e}")


def _compute_atr(result: AnalysisResult, df: pd.DataFrame) -> None:
    """计算 ATR(14)——波动率指标。"""
    import pandas_ta as ta

    try:
        atr = df.ta.atr(length=ATR_PERIOD, append=False)
        if atr is not None and not atr.empty:
            result.atr_14 = round(float(atr.iloc[-1]), 2)
    except Exception as e:
        logger.warning(f"ATR 计算失败: {e}")


def _compute_volume(result: AnalysisResult, df: pd.DataFrame) -> None:
    """计算成交量 SMA。"""
    try:
        vol_sma = df["volume"].rolling(window=VOLUME_SMA_PERIOD).mean()
        result.volume_sma_20 = round(float(vol_sma.iloc[-1]), 2)

        # 量能判断
        current_vol = df["volume"].iloc[-1]
        if current_vol > result.volume_sma_20 * 1.5:
            result.warnings.append("成交量显著放大（>1.5x 均量）")
        elif current_vol < result.volume_sma_20 * 0.5:
            result.warnings.append("成交量显著萎缩（<0.5x 均量）")
    except Exception as e:
        logger.warning(f"成交量计算失败: {e}")


def _compute_trend(result: AnalysisResult, df: pd.DataFrame) -> None:
    """判断趋势方向（基于均线形态和近期价格走势）。"""
    close = df["close"]

    if len(close) < MA_PERIODS[-1]:
        result.trend = "unknown"
        return

    # MA20 > MA50 > MA200 = 上升趋势
    ma20 = close.rolling(window=20).mean()
    ma50 = close.rolling(window=50).mean()
    ma200 = close.rolling(window=200).mean()

    latest_20 = ma20.iloc[-1]
    latest_50 = ma50.iloc[-1]
    latest_200 = ma200.iloc[-1]

    if not all(pd.notna([latest_20, latest_50, latest_200])):
        result.trend = "unknown"
        return

    if latest_20 > latest_50 > latest_200:
        result.trend = "up"
    elif latest_20 < latest_50 < latest_200:
        result.trend = "down"
    else:
        # 短期 vs 长期
        if latest_20 > latest_200:
            result.trend = "sideways_up"
        elif latest_20 < latest_200:
            result.trend = "sideways_down"
        else:
            result.trend = "sideways"
