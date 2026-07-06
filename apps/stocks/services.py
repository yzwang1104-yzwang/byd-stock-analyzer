"""股票分析服务层——所有业务逻辑放这里，views 只做请求分发。

红线 #15: View 不放业务逻辑，逻辑放 services.py。
"""

import io
import json
import os
import statistics
import sys
from pathlib import Path
from typing import Optional


def get_stock_list() -> list[str]:
    """自动发现股票列表：持仓文件 + 缓存中有数据的股票。"""
    codes = set()
    pos_dir = Path(".position_history")
    if pos_dir.exists():
        for f in pos_dir.glob("*.json"):
            if f.stem != "portfolio_snapshots":
                codes.add(f.stem)
    cache_dir = Path(".cache")
    if cache_dir.exists():
        for f in cache_dir.glob("prices_*.csv"):
            codes.add(f.stem.replace("prices_", ""))
    codes.discard("159915"); codes.discard("159919")
    codes.discard("510050"); codes.discard("510300"); codes.discard("512100")
    return sorted(codes)


def get_stock_name(code: str) -> str:
    """从腾讯API获取股票名称，失败返回代码。"""
    import urllib.request, ssl

    cache = {}
    name_file = ".cache/stock_names.json"
    if os.path.exists(name_file):
        try:
            cache = json.load(open(name_file, encoding="utf-8"))
        except Exception:
            pass
    if code in cache:
        return cache[code]

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        prefix = "nq" if code.startswith(("9","8")) else ("sz" if code.startswith(("0","3")) else "sh")
        url = f"https://qt.gtimg.cn/q={prefix}{code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5, context=ctx)
        text = resp.read().decode("gbk", errors="replace")
        for line in text.split("\n"):
            if "~" in line and "none_match" not in line:
                name = line.split("~")[1]
                cache[code] = name
                json.dump(cache, open(name_file, "w"))
                return name
    except Exception:
        pass
    return code


def run_analysis(code: str) -> dict:
    """运行完整分析流水线，返回上下文 dict。

    这是 views 和 CLI 共用的核心分析入口。
    """
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        from core.data_fetcher import fetch_normalized_data, fetch_valuation_data
        data = fetch_normalized_data(stock_code=code, force_refresh=False)

        from core.analyzers.technical import analyze as at
        result = at(data)

        try:
            valuation = fetch_valuation_data(stock_code=code)
        except Exception:
            valuation = None
        from core.analyzers.valuation import analyze as av
        result = av(result, valuation)

        from core.scoring import compute as cs
        sr = cs(result)

        from core.advice import generate as ga
        advice = ga(sr, result, current_price=data.latest_price)

        from core.market_context import get_market_regime, market_boost
        market = get_market_regime()
        advice.score = int(market_boost(advice.score, market))
        advice.score = min(100, max(0, advice.score))

        from core.buy_timing import calculate_path_to_buy
        timing = calculate_path_to_buy(
            advice.score, result.pe_percentile, result.pb_percentile,
            result.trend, data.latest_price, result.ma_20, result.ma_50
        )

        from core.prediction_tracker import get_calibration
        cal = get_calibration(code)

        from core.backtester import predict_direction
        dp = predict_direction(data.prices)
    finally:
        sys.stdout = old

    closes = [p.close for p in data.prices[-100:]]
    all_closes = [p.close for p in data.prices]
    dates = [p.date.isoformat() for p in data.prices[-100:]]

    return {
        "code": code,
        "name": get_stock_name(code),
        "price": data.latest_price,
        "score": advice.score,
        "action": advice.action_label,
        "action_class": advice.action,
        "rationale": advice.rationale,
        "position_pct": advice.position_pct,
        "confidence": advice.confidence,
        "pe_pct": result.pe_percentile,
        "pb_pct": result.pb_percentile,
        "chg_20d": round((data.latest_price - (closes[-21] if len(closes) >= 21 else data.latest_price)) / (closes[-21] if len(closes) >= 21 else 1) * 100, 1) if len(closes) >= 21 else None,
        "trend": result.trend,
        "rsi": result.rsi_14,
        "macd": result.macd,
        "ma20": result.ma_20,
        "ma50": result.ma_50,
        "boll_upper": result.bollinger_upper,
        "boll_lower": result.bollinger_lower,
        "boll_mid": result.bollinger_middle,
        "atr": result.atr_14,
        "direction": dp["direction"],
        "dir_confidence": dp["confidence"],
        "dir_signals": dp["signals"][:3],
        "need_pts": timing["need_pts"],
        "timing_path": timing["paths"][0]["description"][:40] if timing["paths"] else "",
        "at_buy": timing["at_buy"],
        "dates": json.dumps(dates),
        "closes": json.dumps(closes),
        "ma20_series": json.dumps(_calc_sma(closes, 20)),
        "ma50_series": json.dumps(_calc_sma(closes, 50)),
        "boll_upper_series": json.dumps(_calc_boll(closes, 20, 2)[0]),
        "boll_lower_series": json.dumps(_calc_boll(closes, 20, 2)[2]),
        "cal_bias": cal.get("bias_correction", 0),
        "cal_range": cal.get("range_multiplier", 1),
        "low_all": round(min(all_closes), 2) if all_closes else 0,
        "from_low": round((data.latest_price - min(all_closes)) / min(all_closes) * 100, 1) if all_closes else 0,
        "high_all": round(max(all_closes), 2) if all_closes else 0,
        "from_high": round((data.latest_price / max(all_closes) - 1) * 100, 1) if all_closes else 0,
    }


def _calc_sma(values: list, period: int) -> list:
    """使用 pandas 计算简单移动平均（红线 #16：不重复造轮子）。"""
    import pandas as pd
    s = pd.Series(values)
    result = s.rolling(window=period).mean().round(2).tolist()
    return [None if pd.isna(v) else v for v in result]


def _calc_boll(values: list, period: int, std: int) -> tuple:
    """使用 pandas 计算布林带（红线 #16：不重复造轮子）。"""
    import pandas as pd
    import math
    s = pd.Series(values)
    mid = s.rolling(window=period).mean()
    stdev = s.rolling(window=period).std()
    upper = mid + std * stdev
    lower = mid - std * stdev
    return (
        [None if math.isnan(v) else round(v, 2) for v in upper.tolist()],
        [None if math.isnan(v) else round(v, 2) for v in mid.tolist()],
        [None if math.isnan(v) else round(v, 2) for v in lower.tolist()],
    )
