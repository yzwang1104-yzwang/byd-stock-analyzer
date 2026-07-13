"""统一实时扫描引擎 — 所有数据 force_refresh=True，替代缓存扫描。

usage:
    python cli/_scan_realtime.py              # 买入提醒 TOP40
    python cli/_scan_realtime.py --near-low   # 距历史最低 TOP40
    python cli/_scan_realtime.py --top-score  # 评分最高 TOP40
"""

import io
import os
import ssl
import sys
import time
import urllib.request
from typing import Optional

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ====== ST 黑名单 ======
ST_CODES = {"600370", "600745", "688121"}

# ====== 腾讯实时 API ======
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

_name_cache: dict[str, str] = {}

def _get_name(code: str) -> str:
    if code in _name_cache:
        return _name_cache[code]
    try:
        prefix = "nq" if code.startswith(("9", "8")) else ("sz" if code.startswith(("0", "3")) else "sh")
        url = f"https://qt.gtimg.cn/q={prefix}{code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=3, context=_ssl_ctx).read()
        for line in raw.decode("gbk").split("\n"):
            if "~" in line and "none_match" not in line:
                name = line.split("~")[1].strip()
                if name and name != code:
                    _name_cache[code] = name
                    return name
    except Exception:
        pass
    return "?"


def _get_realtime_price(code: str) -> float | None:
    """从腾讯实时行情获取现价，失败返回 None。"""
    try:
        prefix = "nq" if code.startswith(("9", "8")) else ("sz" if code.startswith(("0", "3")) else "sh")
        url = f"https://qt.gtimg.cn/q={prefix}{code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=3, context=_ssl_ctx).read()
        for line in raw.decode("gbk").split("\n"):
            if "~" in line and "none_match" not in line:
                return float(line.split("~")[3])
    except Exception:
        pass
    return None


def _is_st(code: str) -> bool:
    if code in ST_CODES:
        return True
    name = _get_name(code)
    return name.startswith("*ST") or name.startswith("ST")


# ====== 实时数据获取 ======
from core.data_fetcher import fetch_normalized_data


def scan_all(progress: bool = True) -> list[dict]:
    """全量实时扫描，返回所有股票的分析结果。"""
    files = sorted(
        f for f in os.listdir(".cache") if f.startswith("prices_")
    )
    results = []
    st_skip = 0
    err_skip = 0
    total = len(files)
    t0 = time.time()

    for i, f in enumerate(files):
        code = f.replace("prices_", "").replace(".csv", "")
        if code in ("159915", "159919", "510050", "510300", "512100"):
            continue

        # ST 过滤
        if code in ST_CODES:
            st_skip += 1
            continue

        try:
            data = fetch_normalized_data(code, force_refresh=True)
            if not data.prices or len(data.prices) < 50:
                err_skip += 1
                continue

            # ST 名称检查
            name = _get_name(code)
            if name.startswith("*ST") or name.startswith("ST"):
                ST_CODES.add(code)
                st_skip += 1
                continue

            # 优先使用腾讯实时行情，K线收盘价备用
            cur = _get_realtime_price(code)
            if cur is None:
                cur = data.latest_price
            closes = [p.close for p in data.prices]
            all_high = max(p.high for p in data.prices)
            all_low = min(p.low for p in data.prices)
            from_low = (cur - all_low) / all_low * 100
            from_high = (cur / all_high - 1) * 100

            close_s = pd.Series(closes)
            ma20 = float(close_s.rolling(20).mean().iloc[-1])
            ma50 = (
                float(close_s.rolling(50).mean().iloc[-1])
                if len(closes) >= 50
                else ma20
            )
            if ma20 > ma50 * 1.01:
                trend = "UP"
            elif ma20 < ma50 * 0.99:
                trend = "DN"
            else:
                trend = "--"

            delta = close_s.diff()
            gain = delta.clip(lower=0)
            loss = (-delta).clip(lower=0)
            avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi_s = 100 - (100 / (1 + rs))
            rsi_now = float(rsi_s.iloc[-1]) if not np.isnan(rsi_s.iloc[-1]) else 50.0

            chg_5d = (
                (cur - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
            )
            chg_20d = (
                (cur - closes[-21]) / closes[-21] * 100 if len(closes) >= 21 else 0
            )

            results.append(
                {
                    "code": code,
                    "name": name,
                    "cur": round(cur, 2),
                    "low": round(all_low, 2),
                    "high": round(all_high, 2),
                    "from_low": round(from_low, 2),
                    "from_high": round(from_high, 2),
                    "rsi": round(rsi_now, 1),
                    "trend": trend,
                    "ma20": round(ma20, 2),
                    "ma50": round(ma50, 2),
                    "c5": round(chg_5d, 2),
                    "c20": round(chg_20d, 2),
                    "days": len(closes),
                }
            )
        except Exception:
            err_skip += 1

        if progress and (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            print(f"  {i+1}/{total}  OK:{len(results)}  ST:{st_skip}  ERR:{err_skip}  {elapsed:.0f}s")

    elapsed = time.time() - t0
    print(f"完成: {len(results)}只  ST跳过:{st_skip}  ERR:{err_skip}  耗时:{elapsed:.0f}s")
    return results


# ====== 评分算法 ======

def score_buy_alert(r: dict) -> int:
    """买入提醒评分：奖励接近历史低点、RSI超卖。"""
    s = 50
    if r["from_low"] < 3: s += 20
    elif r["from_low"] < 5: s += 16
    elif r["from_low"] < 10: s += 10
    elif r["from_low"] < 20: s += 5
    if r["rsi"] < 20: s += 18
    elif r["rsi"] < 25: s += 13
    elif r["rsi"] < 30: s += 9
    elif r["rsi"] < 35: s += 5
    if r["from_high"] < -60: s += 14
    elif r["from_high"] < -50: s += 10
    elif r["from_high"] < -40: s += 6
    if r["trend"] == "UP": s += 8
    elif r["trend"] == "--": s += 4
    if r["c20"] < -20: s += 6
    elif r["c20"] < -15: s += 3
    return min(100, s)


# ====== CLI ======

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--near-low", action="store_true", help="距历史最低排序")
    parser.add_argument("--top-score", action="store_true", help="买入评分排序")
    parser.add_argument("--limit", type=int, default=40, help="输出行数")
    args = parser.parse_args()

    mode = "buy_alert"
    if args.near_low: mode = "near_low"
    if args.top_score: mode = "top_score"

    print(f"=== 实时扫描 ({mode}) === 正在拉取实时数据...")
    results = scan_all()

    if mode == "near_low":
        results.sort(key=lambda r: r["from_low"])
        title = "已到历史最低"
    elif mode == "top_score":
        for r in results:
            r["score"] = score_buy_alert(r)
        results.sort(key=lambda r: r["score"], reverse=True)
        title = "买入评分"
    else:
        for r in results:
            r["score"] = score_buy_alert(r)
        results = [r for r in results if r["score"] >= 80]
        results.sort(key=lambda r: r["score"], reverse=True)
        title = "买入提醒"

    top = results[: args.limit]
    print(f"\n=== {title} TOP{len(top)} (全量实时) ===\n")
    hdr = f'{"#":>3} {"代码":<8} {"名称":<8} {"现价":>7} {"评分":>4} {"RSI":>4} {"最低":>7} {"距低":>5} {"最高":>7} {"距高":>5} {"趋势":>3}'
    print(hdr)
    print("-" * 76)
    for i, r in enumerate(top, 1):
        s = r.get("score", 0)
        print(
            f'{i:>3} {r["code"]:<8} {r["name"]:<8} {r["cur"]:>7.2f} {s:>4.0f} {r["rsi"]:>4.0f} '
            f'{r["low"]:>7.2f} {r["from_low"]:>+4.0f}% {r["high"]:>7.2f} {r["from_high"]:>+4.0f}% {r["trend"]:>3}'
        )

    if mode == "buy_alert":
        print(f"\n触发:{len(results)}只 | ≥90:{sum(1 for r in results if r.get('score',0)>=90)}")
    print(f"数据: 腾讯API force_refresh=True | ST已过滤")


if __name__ == "__main__":
    main()
