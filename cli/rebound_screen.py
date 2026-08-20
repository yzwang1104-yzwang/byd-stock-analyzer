"""反弹空间筛选 — 现价区间 + 距历史最低2-3元 + 距历史最高≥门槛。

历史最低/最高: 缓存 close 序列的 min/max（与全市场近底筛选口径一致）
输出: 腾讯实时行情核对名称现价，排除 ST/退市/PT，按距低升序
可选 est 参数: 叠加估值分位(PE≤20%或PB≤10%) + 趋势UP 过滤
用法: python cli/rebound_screen.py [距高门槛元] [最低价] [最高价] [est]
"""

import io
import json
import os
import re
import ssl
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

CACHE_DIR = ".cache"
SKIP_PREFIX = {"159", "510", "512", "513", "515", "518", "560", "588"}  # ETF

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def fetch_sina(codes: list[str]) -> dict:
    """新浪批量行情（80只/批），返回 code -> (name, price, last_date)。

    停牌/退市股所有价格字段为 0，调用方据此过滤。
    """
    result: dict = {}
    for i in range(0, len(codes), 80):
        batch = codes[i : i + 80]
        items = []
        for c in batch:
            prefix = "bj" if c.startswith(("4", "8", "92")) else ("sh" if c.startswith(("6", "9")) else "sz")
            items.append(f"{prefix}{c}")
        try:
            url = f"https://hq.sinajs.cn/list={','.join(items)}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"},
            )
            raw = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx).read()
            for line in raw.decode("gbk", errors="replace").split("\n"):
                m = re.search(r'hq_str_(?:sh|sz|bj)(\d{6})="([^"]*)"', line)
                if m and m.group(2):
                    code, p = m.group(1), m.group(2).split(",")
                    name = p[0]
                    try:
                        price = float(p[3]) if len(p) > 3 else 0.0
                    except ValueError:
                        price = 0.0
                    last_date = p[30] if len(p) > 30 else ""
                    result[code] = (name, price, last_date)
        except Exception:
            pass
    return result


def fetch_hist_qq(code: str) -> tuple[float, float] | None:
    """全历史日线高低点 — 优先腾讯前复权，限流时降级新浪（不复权1023根）。"""
    prefix = "nq" if code.startswith(("4", "8", "92")) else ("sh" if code.startswith(("6", "9")) else "sz")
    try:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,2000,qfq"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=15, context=_ssl_ctx).read().decode("utf-8", "replace")
        data = json.loads(raw)
        days = data["data"][f"{prefix}{code}"].get("qfqday") or data["data"][f"{prefix}{code}"].get("day")
        if days:
            lows = [float(d[4]) for d in days]
            highs = [float(d[3]) for d in days]
            return float(min(lows)), float(max(highs))
    except Exception:
        pass
    # 新浪降级（不复权，最近1023根≈4年）
    sprefix = "bj" if code.startswith(("4", "8", "92")) else ("sh" if code.startswith(("6", "9")) else "sz")
    try:
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={sprefix}{code}&scale=240&ma=no&datalen=1023"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=15, context=_ssl_ctx).read().decode("utf-8", "replace")
        bars = json.loads(raw)
        if not isinstance(bars, list) or not bars:
            return None
        lows = [float(b["low"]) for b in bars]
        highs = [float(b["high"]) for b in bars]
        return float(min(lows)), float(max(highs))
    except Exception:
        return None


def read_valuation(code: str) -> tuple[float | None, float | None]:
    """估值历史分位 — PE/PB 当前值在历史正数序列中的百分位。"""
    vp = os.path.join(CACHE_DIR, f"valuation_{code}.csv")
    if not os.path.exists(vp):
        return None, None
    result: list[float | None] = []
    try:
        vdf = pd.read_csv(vp, index_col=0)
        for kind in ("pe", "pb"):
            hcol = f"{kind}_history"
            ccol = f"current_{kind}"
            if hcol in vdf.columns and ccol in vdf.columns:
                raw = str(vdf[hcol].iloc[0])
                if raw and raw != "nan":
                    vals = [float(x) for x in raw.split("|") if x.strip() and float(x) > 0]
                    cur_val = float(vdf[ccol].iloc[0])
                    if vals and len(vals) > 10 and cur_val > 0:
                        pct = float(np.sum(np.array(vals) < cur_val) / len(vals) * 100)
                        result.append(pct)
                        continue
            result.append(None)
    except Exception:
        return None, None
    return result[0], result[1]


def main() -> None:
    min_d_high = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    price_lo = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    price_hi = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
    d_low_max = float(sys.argv[4]) if len(sys.argv) > 4 else 3.0
    est = len(sys.argv) > 5 and sys.argv[5] == "est"
    hits: list[dict] = []
    scanned = 0
    for f in sorted(os.listdir(CACHE_DIR)):
        if not f.startswith("prices_"):
            continue
        code = f.replace("prices_", "").replace(".csv", "")
        if len(code) != 6 or not code.isdigit():
            continue
        if code.startswith(tuple(SKIP_PREFIX)):
            continue
        try:
            df = pd.read_csv(os.path.join(CACHE_DIR, f), usecols=["close"])
            if len(df) < 60:
                continue
            closes = df["close"].values
            cur = float(closes[-1])
            scanned += 1
            if not (price_lo <= cur <= price_hi):
                continue
            low_all = float(closes.min())
            high_all = float(closes.max())
            d_low = cur - low_all
            d_high = high_all - cur
            if d_low <= d_low_max and d_high >= min_d_high:
                ma20 = float(pd.Series(closes).rolling(20).mean().iloc[-1])
                ma50 = float(pd.Series(closes).rolling(50).mean().iloc[-1])
                trend = "UP" if ma20 > ma50 * 1.01 else ("--" if ma20 > ma50 * 0.99 else "DN")
                hits.append(
                    {
                        "code": code,
                        "price": cur,
                        "low": low_all,
                        "high": high_all,
                        "d_low": d_low,
                        "d_high": d_high,
                        "trend": trend,
                    }
                )
        except Exception:
            pass

    print(f"缓存粗筛: {scanned} 只 | 命中: {len(hits)} 只")
    if not hits:
        return

    rt = fetch_sina([h["code"] for h in hits])
    print(f"实时核对: {len(rt)} 只")

    final = []
    suspended = 0
    for h in hits:
        name, price, last_date = rt.get(h["code"], ("?", None, ""))
        if name != "?" and ("ST" in name or "退" in name or "PT" in name):
            continue
        if price is None or price <= 0:
            suspended += 1
            continue
        h["name"] = name if name != "?" else f"({h['code']})"
        h["price"] = round(price, 2)
        # 全历史复核 — 缓存仅500根，历史高低点必须用全量K线确认
        full = fetch_hist_qq(h["code"])
        if full is None:
            continue
        h["low"], h["high"] = full
        h["d_low"] = round(price - h["low"], 2)
        h["d_high"] = round(h["high"] - price, 2)
        time.sleep(0.1)
        # 实时价可能漂出区间，重新校验
        if not (price_lo <= h["price"] <= price_hi):
            continue
        if h["d_low"] > d_low_max or h["d_high"] < min_d_high:
            continue

        pe_pct, pb_pct = read_valuation(h["code"])
        h["pe_pct"], h["pb_pct"] = pe_pct, pb_pct
        if est:
            cheap = (pe_pct is not None and pe_pct <= 20) or (pb_pct is not None and pb_pct <= 10)
            if h["trend"] == "DN" or not cheap:
                continue
        final.append(h)

    final.sort(key=lambda x: -x["d_high"])
    if suspended:
        print(f"停牌/退市剔除: {suspended} 只")
    suffix = " + 估值低 + 趋势UP" if est else ""
    print(f"\n=== 距低2-3元 + 距高≥{min_d_high:.0f}元{suffix}: {len(final)} 只 ===")
    print(
        f'{"代码":<8}{"名称":<12}{"现价":>7}{"最低":>7}{"最高":>7}{"距低":>6}{"距高":>7}'
        f'  {"趋势":<4}{"PE%":>6}{"PB%":>6}'
    )
    for h in final:
        pe_s = f"{h['pe_pct']:.0f}" if h["pe_pct"] is not None else "?"
        pb_s = f"{h['pb_pct']:.0f}" if h["pb_pct"] is not None else "?"
        print(
            f'{h["code"]:<8}{h["name"]:<12}{h["price"]:>7.2f}{h["low"]:>7.2f}{h["high"]:>7.2f}'
            f'{h["d_low"]:>+5.2f}元{h["d_high"]:>+6.1f}元  {h["trend"]:<4}{pe_s:>5}%{pb_s:>5}%'
        )


if __name__ == "__main__":
    main()
