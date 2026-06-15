"""数据获取与缓存——东方财富 push2 API + 百度估值。

设计原则:
- 价格数据: 东方财富 push2 HTTP API（直连，绕过 AkShare 企业网络限制）
- 估值数据: 百度估值 API（通过 AkShare）
- 缓存到 CSV（带时间戳），过期自动重取
"""

import csv
import json
import logging
import os
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from core.config import CACHE_DIR, CACHE_MAX_AGE_HOURS, STOCK_CODE, STOCK_NAME
from core.models import NormalizedData, PriceBar, ValuationData

logger = logging.getLogger(__name__)


# ====== 缓存工具 ======

def _cache_path(filename: str) -> Path:
    cache_dir = Path(CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / filename


def _is_cache_fresh(filepath: Path) -> bool:
    if not filepath.exists():
        return False
    mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
    return (datetime.now() - mtime) < timedelta(hours=CACHE_MAX_AGE_HOURS)


def _read_cache_csv(filepath: Path) -> Optional[list[dict]]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except (OSError, csv.Error) as e:
        logger.warning(f"缓存读取失败 {filepath}: {e}")
        return None


def _write_cache_csv(filepath: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ====== 东方财富 API ======

def _market_code(stock_code: str) -> str:
    """0=深圳, 1=上海"""
    return "0" if stock_code.startswith(("0", "3")) else "1"


def _http_get(url: str, timeout: int = 15) -> dict:
    """HTTP GET → JSON，带 UA 伪装。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_realtime_quote(stock_code: str = STOCK_CODE) -> dict:
    """获取实时行情。

    返回字段:
      f43: 当前价（×100）  f60: 昨收（×100）
      f44: 最高  f45: 最低  f46: 开盘
      f47: 成交量  f48: 成交额
      f51: 52周最高  f52: 52周最低
      f162: PE(静态)  f167: PE(动态)
      f116: 总市值  f117: 流通市值
    """
    secid = f"{_market_code(stock_code)}.{stock_code}"
    url = (
        f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}"
        f"&fields=f43,f44,f45,f46,f47,f48,f50,f51,f52,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170,f171"
    )
    data = _http_get(url, timeout=10)
    if data is None or data.get("data") is None:
        raise RuntimeError(f"东方财富实时行情为空: {stock_code}")
    return data["data"]


# ====== 价格数据 ======

def _fetch_tencent_kline(stock_code: str, days: int) -> list[PriceBar]:
    """从腾讯 API 获取历史日K线（前复权）——企业网络环境最稳定。"""
    prefix = "sz" if stock_code.startswith(("0", "3")) else "sh"
    param = f"{prefix}{stock_code},day,,,{days},qfq"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param}"

    data = _http_get(url, timeout=12)
    stock_data = data.get("data", {}).get(f"{prefix}{stock_code}", {})
    klines = stock_data.get("qfqday") or stock_data.get("day")

    if not klines:
        raise RuntimeError(f"腾讯 K 线数据为空: {stock_code}")

    bars = []
    for row in klines:
        try:
            bars.append(PriceBar(
                date=_parse_date(row[0]),
                open=float(row[1]),
                close=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                volume=int(float(row[5])),
            ))
        except (ValueError, IndexError) as e:
            logger.warning(f"跳过无效行: {row[:3]}... {e}")
            continue

    bars.sort(key=lambda b: b.date)
    return bars


def _fetch_eastmoney_kline(stock_code: str, days: int) -> list[PriceBar]:
    """从东方财富 API 获取 K 线（备用）。"""
    secid = f"{_market_code(stock_code)}.{stock_code}"
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}&klt=101&fqt=1&lmt={days}"
        f"&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57"
    )
    data = _http_get(url, timeout=15)
    klines = data.get("data", {}).get("klines")
    if not klines:
        raise RuntimeError(f"东方财富 K 线数据为空: {stock_code}")

    bars = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 7:
            continue
        try:
            bars.append(PriceBar(
                date=_parse_date(parts[0]),
                open=float(parts[1]),
                close=float(parts[2]),
                high=float(parts[3]),
                low=float(parts[4]),
                volume=int(float(parts[5])),
            ))
        except (ValueError, IndexError) as e:
            logger.warning(f"跳过无效行: {parts[:3]}... {e}")
            continue

    bars.sort(key=lambda b: b.date)
    return bars


def fetch_price_history(
    stock_code: str = STOCK_CODE,
    days: int = 500,
    force_refresh: bool = False,
) -> list[PriceBar]:
    """获取 A 股历史日K线（前复权）。

    优先腾讯 API（企业网络最稳定），东方财富备用。
    """
    cache_file = _cache_path(f"prices_{stock_code}.csv")

    if not force_refresh and _is_cache_fresh(cache_file):
        rows = _read_cache_csv(cache_file)
        if rows:
            logger.info(f"从缓存加载 {stock_code} 价格数据 ({len(rows)} 条)")
            return [_row_to_pricebar(r) for r in rows]

    # 尝试腾讯 API（企业网络最稳定）
    bars = None
    try:
        logger.info(f"从腾讯获取 {stock_code} K线数据...")
        bars = _fetch_tencent_kline(stock_code, days)
    except Exception as e:
        logger.warning(f"腾讯 K 线失败: {e}")

    # 回退东方财富
    if bars is None:
        try:
            logger.info(f"从东方财富获取 {stock_code} K线数据...")
            bars = _fetch_eastmoney_kline(stock_code, days)
        except Exception as e:
            raise RuntimeError(f"所有 K 线数据源均失败: {e}")

    # 写入缓存
    fieldnames = ["date", "open", "high", "low", "close", "volume"]
    _write_cache_csv(cache_file, [
        {"date": b.date.isoformat(), "open": str(b.open), "high": str(b.high),
         "low": str(b.low), "close": str(b.close), "volume": str(b.volume)}
        for b in bars
    ], fieldnames)
    logger.info(f"已缓存 {len(bars)} 条价格数据")

    return bars


# ====== 估值数据 (百度 API) ======

def fetch_valuation_data(
    stock_code: str = STOCK_CODE,
    force_refresh: bool = False,
) -> ValuationData:
    """获取 PE/PB 历史数据（百度估值 API，通过 AkShare）。"""
    cache_file = _cache_path(f"valuation_{stock_code}.csv")

    if not force_refresh and _is_cache_fresh(cache_file):
        rows = _read_cache_csv(cache_file)
        if rows:
            logger.info(f"从缓存加载 {stock_code} 估值数据")
            return _rows_to_valuation(rows)

    try:
        import akshare as ak
    except ImportError:
        raise ImportError("请安装 akshare: pip install akshare>=1.14.0")

    result = ValuationData(stock_code=stock_code, data_date=date.today())

    # PE(TTM)
    try:
        pe_df = ak.stock_zh_valuation_baidu(symbol=stock_code, indicator="市盈率(TTM)", period="近一年")
        if pe_df is not None and not pe_df.empty:
            values = pe_df["value"].dropna().tolist()
            result.pe_history = values
            if values:
                result.current_pe = values[-1]
    except Exception as e:
        logger.warning(f"PE 数据获取失败: {e}")

    # PB
    try:
        pb_df = ak.stock_zh_valuation_baidu(symbol=stock_code, indicator="市净率", period="近一年")
        if pb_df is not None and not pb_df.empty:
            values = pb_df["value"].dropna().tolist()
            result.pb_history = values
            if values:
                result.current_pb = values[-1]
    except Exception as e:
        logger.warning(f"PB 数据获取失败: {e}")

    # 行业估值对比
    try:
        comp_df = ak.stock_zh_valuation_comparison_em(symbol=stock_code)
        if comp_df is not None and not comp_df.empty:
            cols = comp_df.columns.tolist()
            for col in cols:
                if "行业" in col and ("市盈" in col or "PE" in str(col).upper()):
                    result.industry_pe = float(comp_df[col].iloc[0])
                    break
            for col in cols:
                if "行业" in col and ("市净" in col or "PB" in str(col).upper()):
                    result.industry_pb = float(comp_df[col].iloc[0])
                    break
    except Exception as e:
        logger.warning(f"行业数据获取失败: {e}")

    # 写入缓存
    _write_cache_csv(cache_file, [{
        "date": date.today().isoformat(),
        "current_pe": str(result.current_pe) if result.current_pe else "",
        "current_pb": str(result.current_pb) if result.current_pb else "",
        "industry_pe": str(result.industry_pe) if result.industry_pe else "",
        "industry_pb": str(result.industry_pb) if result.industry_pb else "",
        "pe_history": "|".join(str(x) for x in result.pe_history[-252:]),
        "pb_history": "|".join(str(x) for x in result.pb_history[-252:]),
    }], ["date", "current_pe", "current_pb", "industry_pe", "industry_pb", "pe_history", "pb_history"])
    logger.info(f"已缓存估值数据")

    return result


def fetch_normalized_data(
    stock_code: str = STOCK_CODE,
    force_refresh: bool = False,
) -> NormalizedData:
    """一站式数据获取——价格 + 实时行情，归一化为 NormalizedData。"""
    prices = fetch_price_history(stock_code=stock_code, force_refresh=force_refresh)
    is_cached = not force_refresh and _is_cache_fresh(_cache_path(f"prices_{stock_code}.csv"))

    return NormalizedData(
        stock_code=stock_code,
        stock_name=STOCK_NAME if stock_code == STOCK_CODE else stock_code,
        prices=prices,
        data_date=prices[-1].date if prices else date.today(),
        is_cached=is_cached,
        cache_timestamp=datetime.now().isoformat() if is_cached else None,
    )


# ====== Mock 数据 ======

def generate_mock_data(
    stock_code: str = STOCK_CODE,
    days: int = 500,
    start_price: float = 90.0,
    seed: int = 42,
) -> NormalizedData:
    """生成模拟数据——用于离线开发和测试。"""
    import random
    random.seed(seed)

    prices = []
    price = start_price
    today = date.today()

    for i in range(days, 0, -1):
        daily_return = random.gauss(0.0002, 0.025)
        price *= (1 + daily_return)
        price = price * 0.995 + start_price * 0.005
        price = max(price, 10.0)

        bar_date = today - timedelta(days=i)
        prices.append(PriceBar(
            date=bar_date,
            open=round(price * random.uniform(0.99, 1.01), 2),
            high=round(max(price * random.uniform(0.99, 1.01), price) * random.uniform(1.0, 1.03), 2),
            low=round(min(price * random.uniform(0.99, 1.01), price) * random.uniform(0.97, 1.0), 2),
            close=round(price, 2),
            volume=int(random.uniform(5_000_000, 20_000_000)),
        ))

    return NormalizedData(
        stock_code=stock_code,
        stock_name=STOCK_NAME if stock_code == STOCK_CODE else f"Mock-{stock_code}",
        prices=prices,
        data_date=today,
        is_cached=False,
    )


# ====== 内部工具 ======

def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    for fmt in ["%Y-%m-%d", "%Y%m%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"]:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        import pandas as pd
        return pd.Timestamp(s).date()
    except Exception:
        raise ValueError(f"无法解析日期: {value}")


def _row_to_pricebar(row: dict) -> PriceBar:
    return PriceBar(
        date=date.fromisoformat(row["date"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=int(row["volume"]),
    )


def _rows_to_valuation(rows: list[dict]) -> ValuationData:
    r = rows[0]
    pe_str = r.get("pe_history", "")
    pb_str = r.get("pb_history", "")
    return ValuationData(
        stock_code=STOCK_CODE,
        current_pe=float(r["current_pe"]) if r.get("current_pe") else None,
        current_pb=float(r["current_pb"]) if r.get("current_pb") else None,
        industry_pe=float(r["industry_pe"]) if r.get("industry_pe") else None,
        industry_pb=float(r["industry_pb"]) if r.get("industry_pb") else None,
        pe_history=[float(x) for x in pe_str.split("|") if x] if pe_str else [],
        pb_history=[float(x) for x in pb_str.split("|") if x] if pb_str else [],
        data_date=date.fromisoformat(r["date"]) if r.get("date") else None,
    )
