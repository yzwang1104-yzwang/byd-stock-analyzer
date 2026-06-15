"""数据获取与缓存——从 AkShare 拉取比亚迪数据，归一化为 NormalizedData。

设计原则:
- 所有 AkShare 调用在此模块内完成，不泄露原始 DataFrame
- 缓存到 CSV（带时间戳），过期自动重取
- 优雅降级——单个数据源失败不阻断整体流程
"""

import csv
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from core.config import CACHE_DIR, CACHE_MAX_AGE_HOURS, STOCK_CODE, STOCK_NAME
from core.models import NormalizedData, PriceBar, ValuationData

logger = logging.getLogger(__name__)


# ====== 缓存工具 ======

def _cache_path(filename: str) -> Path:
    """获取缓存文件完整路径。"""
    cache_dir = Path(CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / filename


def _is_cache_fresh(filepath: Path) -> bool:
    """检查缓存是否在有效期内。"""
    if not filepath.exists():
        return False
    mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
    age = datetime.now() - mtime
    return age < timedelta(hours=CACHE_MAX_AGE_HOURS)


def _read_cache_csv(filepath: Path) -> Optional[list[dict]]:
    """读取 CSV 缓存为字典列表。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except (OSError, csv.Error) as e:
        logger.warning(f"缓存读取失败 {filepath}: {e}")
        return None


def _write_cache_csv(filepath: Path, rows: list[dict], fieldnames: list[str]) -> None:
    """写入 CSV 缓存。"""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ====== 数据获取 ======


def fetch_price_history(
    stock_code: str = STOCK_CODE,
    start_date: str = "20150101",
    end_date: Optional[str] = None,
    force_refresh: bool = False,
) -> list[PriceBar]:
    """获取 A 股历史日线数据（前复权）。

    Args:
        stock_code: 股票代码，默认 002594（比亚迪）
        start_date: 起始日期 YYYYMMDD
        end_date: 结束日期 YYYYMMDD，None = 今天
        force_refresh: 强制刷新，忽略缓存

    Returns:
        PriceBar 列表，按日期升序
    """
    if end_date is None:
        end_date = date.today().strftime("%Y%m%d")

    cache_file = _cache_path(f"prices_{stock_code}.csv")

    # 尝试从缓存读取
    if not force_refresh and _is_cache_fresh(cache_file):
        rows = _read_cache_csv(cache_file)
        if rows:
            logger.info(f"从缓存加载 {stock_code} 价格数据 ({len(rows)} 条)")
            return [_row_to_pricebar(r) for r in rows]

    # 从 AkShare 获取
    try:
        import akshare as ak
    except ImportError:
        raise ImportError("请安装 akshare: pip install akshare>=1.14.0")

    logger.info(f"从 AkShare 获取 {stock_code} 价格数据...")
    df = ak.stock_zh_a_hist(
        symbol=stock_code,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq",  # 前复权——关键！
    )

    if df is None or df.empty:
        raise RuntimeError(f"AkShare 返回空数据: {stock_code}")

    # AkShare 返回中文列名: 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
    bars = []
    for _, row in df.iterrows():
        try:
            bar = PriceBar(
                date=_parse_date(row["日期"]),
                open=float(row["开盘"]),
                high=float(row["最高"]),
                low=float(row["最低"]),
                close=float(row["收盘"]),
                volume=int(row["成交量"]),
            )
            bars.append(bar)
        except (ValueError, KeyError) as e:
            logger.warning(f"跳过无效数据行: {e}")
            continue

    bars.sort(key=lambda b: b.date)

    # 写入缓存
    fieldnames = ["date", "open", "high", "low", "close", "volume"]
    cache_rows = [
        {
            "date": b.date.isoformat(),
            "open": str(b.open),
            "high": str(b.high),
            "low": str(b.low),
            "close": str(b.close),
            "volume": str(b.volume),
        }
        for b in bars
    ]
    _write_cache_csv(cache_file, cache_rows, fieldnames)
    logger.info(f"已缓存 {len(bars)} 条价格数据到 {cache_file}")

    return bars


def fetch_valuation_data(
    stock_code: str = STOCK_CODE,
    force_refresh: bool = False,
) -> ValuationData:
    """获取 PE/PB 估值数据和行业对比。

    Args:
        stock_code: 股票代码
        force_refresh: 强制刷新

    Returns:
        ValuationData（部分字段可能为 None 表示获取失败）
    """
    cache_file = _cache_path(f"valuation_{stock_code}.csv")

    # 尝试缓存
    if not force_refresh and _is_cache_fresh(cache_file):
        rows = _read_cache_csv(cache_file)
        if rows:
            logger.info(f"从缓存加载 {stock_code} 估值数据")
            return _rows_to_valuation(rows)

    # 从 AkShare 获取
    try:
        import akshare as ak
    except ImportError:
        raise ImportError("请安装 akshare: pip install akshare>=1.14.0")

    result = ValuationData(stock_code=stock_code, data_date=date.today())

    # 1. PE/PB 历史
    try:
        logger.info(f"获取 {stock_code} PE/PB 数据...")
        pe_df = ak.stock_a_pe(symbol=stock_code)
        if pe_df is not None and not pe_df.empty:
            # 列名可能为: 日期, 市盈率, 市净率
            result.pe_history = pe_df.get("市盈率", pe_df.iloc[:, 1]).dropna().tolist()
            result.pb_history = pe_df.get("市净率", pe_df.iloc[:, 2]).dropna().tolist()
            if result.pe_history:
                result.current_pe = result.pe_history[-1]
            if result.pb_history:
                result.current_pb = result.pb_history[-1]
    except Exception as e:
        logger.warning(f"获取 PE/PB 数据失败: {e}")

    # 2. 行业对比
    try:
        logger.info(f"获取行业估值数据...")
        industry_df = ak.stock_a_lg_indicator()
        if industry_df is not None and not industry_df.empty:
            # 查找比亚迪所在行业（汽车制造业）
            auto_row = industry_df[industry_df.iloc[:, 0].str.contains("汽车", na=False)]
            if not auto_row.empty:
                result.industry_pe = float(auto_row.iloc[0, 1])  # PE
                result.industry_pb = float(auto_row.iloc[0, 2])  # PB
    except Exception as e:
        logger.warning(f"获取行业数据失败: {e}")

    # 写入缓存
    cache_rows = [
        {
            "date": date.today().isoformat(),
            "current_pe": str(result.current_pe) if result.current_pe else "",
            "current_pb": str(result.current_pb) if result.current_pb else "",
            "industry_pe": str(result.industry_pe) if result.industry_pe else "",
            "industry_pb": str(result.industry_pb) if result.industry_pb else "",
            "pe_history": "|".join(str(x) for x in result.pe_history[-252:]),  # 最近一年
            "pb_history": "|".join(str(x) for x in result.pb_history[-252:]),
        }
    ]
    _write_cache_csv(
        cache_file, cache_rows,
        ["date", "current_pe", "current_pb", "industry_pe", "industry_pb", "pe_history", "pb_history"],
    )
    logger.info(f"已缓存估值数据到 {cache_file}")

    return result


def fetch_normalized_data(
    stock_code: str = STOCK_CODE,
    force_refresh: bool = False,
) -> NormalizedData:
    """一站式数据获取——价格 + 估值，归一化为 NormalizedData。

    Args:
        stock_code: 股票代码
        force_refresh: 强制刷新所有数据

    Returns:
        NormalizedData，包含价格数据和元信息
    """
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


# ====== 内部工具 ======


def _parse_date(value) -> date:
    """解析多种日期格式。"""
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
    # pandas Timestamp
    try:
        import pandas as pd
        return pd.Timestamp(s).date()
    except Exception:
        raise ValueError(f"无法解析日期: {value}")


def _row_to_pricebar(row: dict) -> PriceBar:
    """CSV 行 → PriceBar。"""
    return PriceBar(
        date=date.fromisoformat(row["date"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=int(row["volume"]),
    )


def generate_mock_data(
    stock_code: str = STOCK_CODE,
    days: int = 500,
    start_price: float = 90.0,
    seed: int = 42,
) -> NormalizedData:
    """生成模拟数据——用于离线开发和测试。

    生成近似真实走势的 OHLCV 数据（含趋势+噪声）。
    仅在真实数据不可用时使用。
    """
    import random
    random.seed(seed)

    prices = []
    price = start_price
    today = date.today()

    for i in range(days, 0, -1):
        # 均值回归随机游走：价格围绕 start_price 波动
        daily_return = random.gauss(0.0002, 0.025)  # 日均 +0.02%, σ=2.5%
        price *= (1 + daily_return)
        price = price * 0.995 + start_price * 0.005  # 均值回归拉力 0.5%
        price = max(price, 10.0)  # 防止负数

        bar_date = today - timedelta(days=i)
        open_price = price * random.uniform(0.99, 1.01)
        high_price = max(open_price, price) * random.uniform(1.0, 1.03)
        low_price = min(open_price, price) * random.uniform(0.97, 1.0)
        close_price = price
        volume = int(random.uniform(5_000_000, 20_000_000))

        prices.append(PriceBar(
            date=bar_date,
            open=round(open_price, 2),
            high=round(high_price, 2),
            low=round(low_price, 2),
            close=round(close_price, 2),
            volume=volume,
        ))

    return NormalizedData(
        stock_code=stock_code,
        stock_name=STOCK_NAME if stock_code == STOCK_CODE else f"Mock-{stock_code}",
        prices=prices,
        data_date=today,
        is_cached=False,
    )


def _rows_to_valuation(rows: list[dict]) -> ValuationData:
    """CSV 行 → ValuationData。"""
    r = rows[0]
    pe_hist_str = r.get("pe_history", "")
    pb_hist_str = r.get("pb_history", "")
    return ValuationData(
        stock_code=STOCK_CODE,
        current_pe=float(r["current_pe"]) if r.get("current_pe") else None,
        current_pb=float(r["current_pb"]) if r.get("current_pb") else None,
        industry_pe=float(r["industry_pe"]) if r.get("industry_pe") else None,
        industry_pb=float(r["industry_pb"]) if r.get("industry_pb") else None,
        pe_history=[float(x) for x in pe_hist_str.split("|") if x] if pe_hist_str else [],
        pb_history=[float(x) for x in pb_hist_str.split("|") if x] if pb_hist_str else [],
        data_date=date.fromisoformat(r["date"]) if r.get("date") else None,
    )
