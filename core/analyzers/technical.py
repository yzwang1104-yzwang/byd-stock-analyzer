"""技术指标分析——MA, MACD, RSI, 布林带, ATR, 成交量。

设计原则:
- NormalizedData 输入 → AnalysisResult 输出（纯函数，无副作用）
- 所有指标使用 shift(1) 防止前瞻偏差
- 使用 pandas-ta 函数式调用（ta.rsi(series)），而非 df.ta 访问器
  （df.ta 访问器在数据不足时返回原始 DataFrame，导致浮点数转换失败）
- 所有指标计算带 talib=False（本环境未安装 TA-Lib）
"""

import logging
from datetime import date

import numpy as np
import pandas as pd
import pandas_ta as ta
import warnings as _w

# 抑制 DataFrame 打印 + pandas-ta 警告
pd.set_option("display.max_rows", 0)
pd.set_option("display.max_columns", 0)
_w.filterwarnings("ignore", category=FutureWarning)
_w.filterwarnings("ignore", message=".*pandas_ta.*")

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

    n_rows = len(df_safe)
    enough = n_rows >= 50
    minimal = n_rows >= 14

    if not minimal:
        result.warnings.append(f"数据不足（仅 {n_rows} 条），大多数技术指标无法计算")

    try:
        # 1. 移动均线
        _compute_ma(result, df_safe)

        # 2. MACD
        if enough:
            _compute_macd(result, df_safe)

        # 3. RSI
        if minimal:
            _compute_rsi(result, df_safe)

        # 4. 布林带
        if enough:
            _compute_bollinger(result, df_safe)

        # 5. ATR
        if minimal:
            _compute_atr(result, df_safe)

        # 6. 成交量均线
        _compute_volume(result, df_safe)

        # 7. 趋势判断
        _compute_trend(result, df_safe)

    except Exception as e:
        logger.error(f"指标计算失败: {e}")
        result.warnings.append(f"指标计算异常: {e}")
        result.data_quality = "degraded"

    # 填充最新收盘价（供 scoring.py 布林带位置计算使用）
    if not df.empty and "close" in df.columns:
        result.latest_close = float(df["close"].iloc[-1])

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
    """计算 MACD 并检测金叉/死叉（函数式调用，talib=False）。"""
    try:
        close = df["close"].astype(float)
        macd_df = ta.macd(
            close,
            fast=MACD_PARAMS["fast"],
            slow=MACD_PARAMS["slow"],
            signal=MACD_PARAMS["signal"],
            talib=False,
        )
        if macd_df is None or macd_df.empty:
            return

        # pandas-ta 函数式调用返回: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
        col_macd = [c for c in macd_df.columns if c.startswith("MACD_") and "s" not in c.split("_")[-1] and "h" not in c.split("_")[-1]]
        col_signal = [c for c in macd_df.columns if "MACDs" in c]
        col_hist = [c for c in macd_df.columns if "MACDh" in c]

        if not (col_macd and col_signal and col_hist):
            return

        val_macd = macd_df[col_macd[0]].dropna()
        val_signal = macd_df[col_signal[0]].dropna()
        val_hist = macd_df[col_hist[0]].dropna()

        if len(val_macd) < 1:
            return

        result.macd = round(float(val_macd.iloc[-1]), 4)
        result.macd_signal = round(float(val_signal.iloc[-1]), 4)
        result.macd_histogram = round(float(val_hist.iloc[-1]), 4)

        # 金叉/死叉检测
        if len(val_macd) >= 2 and len(val_signal) >= 2:
            prev_macd = val_macd.iloc[-2]
            prev_signal = val_signal.iloc[-2]
            curr_macd = val_macd.iloc[-1]
            curr_signal = val_signal.iloc[-1]

            if prev_macd <= prev_signal and curr_macd > curr_signal:
                result.warnings.append("MACD 金叉信号")
            elif prev_macd >= prev_signal and curr_macd < curr_signal:
                result.warnings.append("MACD 死叉信号")
    except (Exception, IndexError) as e:
        logger.warning(f"MACD 计算失败: {e}")


def _compute_rsi(result: AnalysisResult, df: pd.DataFrame) -> None:
    """计算 RSI(14) 并判断超买超卖（函数式调用，talib=False）。"""
    try:
        close = df["close"].astype(float)
        rsi = ta.rsi(close, length=RSI_PERIOD, talib=False)
        if rsi is None or rsi.empty:
            return
        val = rsi.dropna()
        if len(val) < 1:
            return
        result.rsi_14 = round(float(val.iloc[-1]), 2)

        if result.rsi_14 <= RSI_OVERSOLD:
            result.warnings.append(f"RSI 超卖 ({result.rsi_14})")
        elif result.rsi_14 >= RSI_OVERBOUGHT:
            result.warnings.append(f"RSI 超买 ({result.rsi_14})")
    except Exception as e:
        logger.warning(f"RSI 计算失败: {e}")


def _compute_bollinger(result: AnalysisResult, df: pd.DataFrame) -> None:
    """计算布林带(20,2)（函数式调用，talib=False）。"""
    try:
        close = df["close"].astype(float)
        bb = ta.bbands(
            close,
            length=BOLLINGER_PARAMS["period"],
            std=BOLLINGER_PARAMS["std_dev"],
            talib=False,
        )
        if bb is None or bb.empty:
            return

        # 函数式调用返回列名含浮点精度: BBL_20_2.0_2.0, BBM_20_2.0_2.0, BBU_20_2.0_2.0...
        col_upper = [c for c in bb.columns if c.startswith("BBU_")]
        col_mid = [c for c in bb.columns if c.startswith("BBM_")]
        col_lower = [c for c in bb.columns if c.startswith("BBL_")]

        if not (col_upper and col_mid and col_lower):
            return

        up = bb[col_upper[0]].dropna()
        mid = bb[col_mid[0]].dropna()
        low = bb[col_lower[0]].dropna()

        if len(up) < 1:
            return

        result.bollinger_upper = round(float(up.iloc[-1]), 2)
        result.bollinger_middle = round(float(mid.iloc[-1]), 2)
        result.bollinger_lower = round(float(low.iloc[-1]), 2)

        # 价格位置判断
        close_val = df["close"].iloc[-1]
        if close_val <= result.bollinger_lower:
            result.warnings.append("价格触及布林带下轨——可能超卖")
        elif close_val >= result.bollinger_upper:
            result.warnings.append("价格触及布林带上轨——可能超买")
    except Exception as e:
        logger.warning(f"布林带计算失败: {e}")


def _compute_atr(result: AnalysisResult, df: pd.DataFrame) -> None:
    """计算 ATR(14)——波动率指标（函数式调用，talib=False）。"""
    try:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        atr = ta.atr(high, low, close, length=ATR_PERIOD, talib=False)
        if atr is None or atr.empty:
            return
        val = atr.dropna()
        if len(val) < 1:
            return
        result.atr_14 = round(float(val.iloc[-1]), 2)
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
    """判断趋势方向（基于均线形态和近期价格走势）。

    分级检测:
    - >=200条: MA20 vs MA50 vs MA200 三代均线
    - >=50条:  MA20 vs MA50
    - >=20条:  MA20 斜率
    """
    close = df["close"]
    n = len(close)

    if n < 20:
        result.trend = "unknown"
        return

    ma20 = close.rolling(window=20).mean()
    ma50 = close.rolling(window=50).mean() if n >= 50 else None
    ma200 = close.rolling(window=200).mean() if n >= 200 else None

    latest_20 = ma20.iloc[-1]
    latest_50 = ma50.iloc[-1] if ma50 is not None else None
    latest_200 = ma200.iloc[-1] if ma200 is not None else None

    if latest_200 is not None and latest_50 is not None:
        # 三代均线齐全
        if latest_20 > latest_50 > latest_200:
            result.trend = "up"
        elif latest_20 < latest_50 < latest_200:
            result.trend = "down"
        else:
            result.trend = "sideways"
    elif latest_50 is not None:
        # MA20 vs MA50
        if latest_20 > latest_50:
            result.trend = "up"
        elif latest_20 < latest_50:
            result.trend = "down"
        else:
            result.trend = "sideways"
    else:
        # 仅 MA20 斜率
        ma20_slope = (ma20.iloc[-1] - ma20.iloc[-5]) / ma20.iloc[-5] if n >= 5 else 0
        if ma20_slope > 0.01:
            result.trend = "up"
        elif ma20_slope < -0.01:
            result.trend = "down"
        else:
            result.trend = "sideways"

    return
