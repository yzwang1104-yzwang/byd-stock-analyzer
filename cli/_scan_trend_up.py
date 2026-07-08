"""趋势过滤买入推荐 — 仅推荐趋势 UP/-- 的股票，淘汰飞刀。

usage:
    python cli/_scan_trend_up.py
"""

import io
import os
import ssl
import sys
import urllib.request

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ST_CODES = {"600370", "600745", "688121"}
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

_name_cache = {}


def _get_name(code: str) -> str:
    if code in _name_cache:
        return _name_cache[code]
    try:
        prefix = "nq" if code.startswith(("9", "8")) else ("sz" if code.startswith(("0", "3")) else "sh")
        url = f"https://qt.gtimg.cn/q={prefix}{code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=2, context=_ssl_ctx).read()
        for line in raw.decode("gbk").split("\n"):
            if "~" in line and "none_match" not in line:
                name = line.split("~")[1].strip()
                if name and name != code:
                    _name_cache[code] = name
                    return name
    except Exception:
        pass
    return "?"


def main():
    from core.data_fetcher import fetch_normalized_data

    # Step 1: 从缓存快速筛选趋势
    candidates = []
    for f in sorted(os.listdir(".cache")):
        if not f.startswith("prices_"):
            continue
        code = f.replace("prices_", "").replace(".csv", "")
        if code in ("159915", "159919", "510050", "510300", "512100"):
            continue
        if code in ST_CODES:
            continue
        try:
            df = pd.read_csv(f".cache/prices_{code}.csv", index_col=0, parse_dates=True)
            if len(df) < 50:
                continue
            close = df["close"]
            ma20 = float(close.rolling(20).mean().iloc[-1])
            ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else ma20
            if ma20 > ma50 * 0.99:
                candidates.append(code)
        except Exception:
            pass

    print(f"趋势UP/--候选: {len(candidates)} 只，实时拉取中...")

    # Step 2: force_refresh 并评分
    results = []
    for i, code in enumerate(candidates):
        try:
            data = fetch_normalized_data(code, force_refresh=True)
            if not data.prices or len(data.prices) < 50:
                continue
            name = _get_name(code)
            if name.startswith("*ST") or name.startswith("ST"):
                ST_CODES.add(code)
                continue

            cur = data.latest_price
            closes = [p.close for p in data.prices]
            all_high = max(p.high for p in data.prices)
            all_low = min(p.low for p in data.prices)
            from_low = (cur - all_low) / all_low * 100
            from_high = (cur / all_high - 1) * 100

            close_s = pd.Series(closes)
            ma20_v = float(close_s.rolling(20).mean().iloc[-1])
            ma50_v = float(close_s.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else ma20_v
            if ma20_v > ma50_v * 1.01:
                trend = "UP"
            elif ma20_v > ma50_v * 0.99:
                trend = "--"
            else:
                continue

            delta = close_s.diff()
            gain = delta.clip(lower=0)
            loss = (-delta).clip(lower=0)
            avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi_s = 100 - (100 / (1 + rs))
            rsi_now = float(rsi_s.iloc[-1]) if not np.isnan(rsi_s.iloc[-1]) else 50.0
            chg_5d = (cur - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
            chg_20d = (cur - closes[-21]) / closes[-21] * 100 if len(closes) >= 21 else 0

            score = 50
            if from_low < 5: score += 15
            elif from_low < 10: score += 10
            elif from_low < 20: score += 5
            if rsi_now < 30: score += 12
            elif rsi_now < 40: score += 6
            if trend == "UP": score += 12
            elif trend == "--": score += 4
            if from_high < -40: score += 8
            if chg_20d < -15: score += 5
            score = min(100, score)

            results.append({
                "code": code, "name": name, "cur": round(cur, 2), "score": score,
                "rsi": round(rsi_now, 1), "low": round(all_low, 2),
                "from_low": round(from_low, 1), "high": round(all_high, 2),
                "from_high": round(from_high, 1), "trend": trend,
                "c5": round(chg_5d, 1), "c20": round(chg_20d, 1),
            })
        except Exception:
            pass
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(candidates)}")

    results.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n=== 趋势过滤买入推荐 TOP40 (仅UP/--，淘汰飞刀) ===\n")
    hdr = f'{"#":>3} {"代码":<8} {"名称":<8} {"现价":>7} {"评分":>4} {"RSI":>4} {"最低":>7} {"距低":>5} {"最高":>7} {"距高":>5} {"趋势":>3} {"5日":>5} {"20日":>5}'
    print(hdr)
    print("-" * 88)
    for i, r in enumerate(results[:40], 1):
        print(
            f'{i:>3} {r["code"]:<8} {r["name"]:<8} {r["cur"]:>7.2f} {r["score"]:>4.0f} {r["rsi"]:>4.0f} '
            f'{r["low"]:>7.2f} {r["from_low"]:>+4.0f}% {r["high"]:>7.2f} {r["from_high"]:>+4.0f}% '
            f'{r["trend"]:>3} {r["c5"]:>+4.0f}% {r["c20"]:>+4.0f}%'
        )

    up = sum(1 for r in results[:40] if r["trend"] == "UP")
    print(f"\n候选:{len(candidates)} → 刷新:{len(results)} | UP:{up}/40 | 数据:force_refresh=True")


if __name__ == "__main__":
    main()
