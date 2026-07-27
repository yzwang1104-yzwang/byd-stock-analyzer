"""快速买入扫描 — 缓存秒级评分 + 腾讯实时行情名称/价格。

只扫描趋势 UP/-- 的股票，TOP40 用腾讯实时数据。
"""

import io, os, ssl, sys, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

CACHE_DIR = ".cache"
ST_CODES = {"600370", "600745", "688121"}
SKIP_CODES = {"159915", "159919", "510050", "510300", "512100"}

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _fetch_realtime_batch(codes: list[str]) -> dict:
    """批量从腾讯API获取实时名称+价格。一次请求最多~50只。"""
    result = {}
    for i in range(0, len(codes), 50):
        batch = codes[i : i + 50]
        items = []
        for c in batch:
            prefix = "nq" if c.startswith(("9", "8")) else ("sz" if c.startswith(("0", "3")) else "sh")
            items.append(f"{prefix}{c}")
        try:
            url = f"https://qt.gtimg.cn/q={','.join(items)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx).read()
            for line in raw.decode("gbk", errors="replace").split("\n"):
                if "~" in line and "none_match" not in line:
                    parts = line.split("~")
                    if len(parts) >= 4:
                        # parts[0] like 'v_sh600104="1' → extract code
                        raw_head = parts[0]
                        code_raw = ""
                        for ch in raw_head:
                            if ch.isdigit():
                                code_raw += ch
                            elif code_raw:
                                break
                        code_raw = code_raw[-6:] if len(code_raw) >= 6 else code_raw
                        name = parts[1].strip()
                        try:
                            price = float(parts[3])
                        except ValueError:
                            price = None
                        if code_raw:
                            result[code_raw] = {"name": name, "price": price}
        except Exception:
            pass
    return result


def main():
    results = []
    codes_scanned = 0
    up_count = 0
    sideways_count = 0

    for f in sorted(os.listdir(CACHE_DIR)):
        if not f.startswith("prices_"):
            continue
        code = f.replace("prices_", "").replace(".csv", "")
        if code in SKIP_CODES or code in ST_CODES:
            continue
        if not (code.startswith(("0", "3", "6", "9", "8"))):
            continue
        if len(code) != 6:
            continue

        try:
            df = pd.read_csv(os.path.join(CACHE_DIR, f), index_col=0, parse_dates=True)
            if len(df) < 50:
                continue
            close = df["close"]
            closes = close.values
            cur = float(close.iloc[-1])
            codes_scanned += 1

            ma20 = float(close.rolling(20).mean().iloc[-1])
            ma50 = float(close.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else ma20

            if ma20 > ma50 * 1.01:
                trend = "UP"
                up_count += 1
            elif ma20 > ma50 * 0.99:
                trend = "--"
                sideways_count += 1
            else:
                continue

            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = (-delta).clip(lower=0)
            avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
            rs_val = avg_gain / avg_loss.replace(0, np.nan)
            rsi_s = 100 - (100 / (1 + rs_val))
            rsi = float(rsi_s.iloc[-1]) if not np.isnan(rsi_s.iloc[-1]) else 50

            low_all = float(np.min(closes))
            high_all = float(np.max(closes))
            from_low = (cur - low_all) / low_all * 100
            from_high = (cur / high_all - 1) * 100

            chg_3d = (cur - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 else 0
            chg_5d = (cur - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
            chg_20d = (cur - closes[-21]) / closes[-21] * 100 if len(closes) >= 21 else 0

            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            dif = ema12 - ema26
            dea = dif.ewm(span=9, adjust=False).mean()
            macd = float(dif.iloc[-1] - dea.iloc[-1])

            score = 50.0
            if from_low < 5: score += 18
            elif from_low < 10: score += 12
            elif from_low < 20: score += 6
            elif from_low < 30: score += 3
            if trend == "UP":
                if rsi < 25: score += 15
                elif rsi < 30: score += 10
                elif rsi < 35: score += 6
                score += 12
            elif trend == "--":
                if rsi < 25: score += 10
                elif rsi < 30: score += 6
                score += 5
            if from_high < -60: score += 10
            elif from_high < -40: score += 7
            elif from_high < -25: score += 4
            if macd > 0: score += 5
            if chg_20d < -15: score += 5

            pe_pct = _read_val(code, "pe")
            pb_pct = _read_val(code, "pb")
            if pe_pct is not None:
                if pe_pct < 15: score += 8
                elif pe_pct < 30: score += 4
                elif pe_pct > 80: score -= 5
            if pb_pct is not None:
                if pb_pct < 15: score += 5
                elif pb_pct > 80: score -= 3

            momentum_accel = chg_3d - chg_5d
            falling_knife = trend == "DN" and chg_3d < -3 and momentum_accel < -1
            if falling_knife: score -= 10

            score = max(0, min(100, score))

            signals = []
            if rsi < 30: signals.append(f"RSI{rsi:.0f}")
            if pe_pct is not None and pe_pct < 15: signals.append(f"PE{pe_pct:.0f}%")
            if pb_pct is not None and pb_pct < 15: signals.append(f"PB{pb_pct:.0f}%")
            if from_low < 5: signals.append(f"近低{from_low:.0f}%")
            if from_high < -60: signals.append(f"反弹{abs(from_high):.0f}%")
            if macd > 0: signals.append("MACD↑")
            if trend == "UP": signals.append("趋势UP")
            sig = " ".join(signals) if signals else "—"

            results.append({
                "code": code, "price": cur, "score": round(score, 1),
                "rsi": round(rsi, 1), "trend": trend,
                "from_low": round(from_low, 1), "from_high": round(from_high, 1),
                "low_all": low_all, "high_all": high_all,
                "chg_5d": round(chg_5d, 1), "chg_20d": round(chg_20d, 1),
                "macd": round(macd, 4), "pe_pct": pe_pct, "pb_pct": pb_pct,
                "signals": sig, "data_days": len(closes),
            })
        except Exception:
            pass

    results.sort(key=lambda x: x["score"], reverse=True)

    # ---- 批量获取 TOP50 实时行情 ----
    top_codes = [r["code"] for r in results[:50]]
    print(f"扫描: {codes_scanned}只 | UP:{up_count} | --:{sideways_count} | 有效:{len(results)}")
    print(f"正在获取 TOP50 实时行情...", end=" ", flush=True)
    rt_data = _fetch_realtime_batch(top_codes)
    print(f"获取 {len(rt_data)} 只")

    # 用实时数据替换 TOP40
    skipped = 0
    displayed = 0
    top_results = []
    for r in results:
        if displayed >= 40:
            break
        code = r["code"]
        rt = rt_data.get(code, {})
        name = rt.get("name", "?")
        rt_price = rt.get("price")

        # 过滤退市/ST 股（通过名称）
        if name and ("退市" in name or "PT" in name or name.startswith("*ST") or name.startswith("ST")):
            ST_CODES.add(code)
            skipped += 1
            continue

        if rt_price and rt_price > 0:
            # 用实时价重新算距低/距高
            r["price"] = round(rt_price, 2)
            if r["low_all"] > 0:
                r["from_low"] = round((rt_price - r["low_all"]) / r["low_all"] * 100, 1)
            if r["high_all"] > 0:
                r["from_high"] = round((rt_price / r["high_all"] - 1) * 100, 1)

        r["name"] = name if name != "?" else f"({code})"
        top_results.append(r)
        displayed += 1

    print()
    print("═" * 100)
    print("  🔥 今日买入推荐 TOP40 (趋势UP/-- | 腾讯实时行情)")
    print("═" * 100)
    print(f'  {"#":>3} {"代码":<8} {"名称":<8} {"现价":>7} {"评分":>5} {"趋势":<4} {"RSI":>5} {"距低%":>6} {"距高%":>7} {"PE%":>5} {"PB%":>5} {"5日%":>6} {"信号"}')
    print("-" * 100)

    for i, r in enumerate(top_results, 1):
        pe_str = f'{r["pe_pct"]:.0f}' if r["pe_pct"] is not None else "?"
        pb_str = f'{r["pb_pct"]:.0f}' if r["pb_pct"] is not None else "?"
        bar = "🔥" if r["score"] >= 85 else ("🟢" if r["score"] >= 70 else "🟡")
        print(
            f'  {bar} {i:>2} {r["code"]:<8} {r["name"]:<8} {r["price"]:>7.2f} {r["score"]:>5.0f} '
            f'{r["trend"]:<4} {r["rsi"]:>5.0f} {r["from_low"]:>6.1f} {r["from_high"]:>7.1f} '
            f'{pe_str:>5} {pb_str:>5} {r["chg_5d"]:>+5.0f}% {r["signals"][:55]}'
        )

    print()
    cheap_pe = [r for r in top_results if r.get("pe_pct") and r["pe_pct"] < 20]
    cheap_pb = [r for r in top_results if r.get("pb_pct") and r["pb_pct"] < 20]
    up_n = sum(1 for r in top_results if r["trend"] == "UP")
    print(f"  PE<20%: {len(cheap_pe)}只 | PB<20%: {len(cheap_pb)}只 | UP: {up_n}/40 | 过滤退市/ST: {skipped}只")
    print(f"  数据: 缓存评分(K线收盘价) + 腾讯实时行情(现价/名称)")

    # 统计
    print()
    print("═" * 100)
    print("  📊 评分分布")
    print("═" * 100)
    r90 = [r for r in top_results if r["score"] >= 90]
    r80 = [r for r in top_results if 80 <= r["score"] < 90]
    r70 = [r for r in top_results if 70 <= r["score"] < 80]
    print(f"  🔥 ≥90: {len(r90)}只  |  🟢 80-89: {len(r80)}只  |  🟡 70-79: {len(r70)}只")

    if r90:
        print(f"\n  🔥 评分≥90:")
        for r in r90:
            print(f'     {r["code"]} {r["name"]} | {r["score"]:.0f}分 | RSI{r["rsi"]:.0f} | 距低{r["from_low"]:.0f}% | {r["signals"]}')

    print()
    print("═" * 100)
    print("  ⚠️ 免责声明：以上分析基于历史数据和量化模型，仅供参考，不构成投资建议。")
    print("═" * 100)


def _read_val(code, kind):
    vp = os.path.join(CACHE_DIR, f"valuation_{code}.csv")
    if not os.path.exists(vp):
        return None
    try:
        vdf = pd.read_csv(vp, index_col=0)
        hcol = f"{kind}_history"
        ccol = f"current_{kind}"
        if hcol in vdf.columns and ccol in vdf.columns:
            raw = str(vdf[hcol].iloc[0])
            if raw and raw != "nan":
                vals = [float(x) for x in raw.split("|") if x.strip()]
                if vals and len(vals) > 10:
                    cur_val = float(vdf[ccol].iloc[0])
                    pct = np.sum(np.array(vals) < cur_val) / len(vals) * 100
                    return float(pct)
    except Exception:
        pass
    return None


if __name__ == "__main__":
    main()
