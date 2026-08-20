"""近底筛选 — 在「5-10元 + 距历史最低≤2元」名单上叠加估值低位 + 趋势向上条件。

输入: 全市场筛选结果文件（代码 名称 现价 历史最低 高出金额）
条件:
  1. 估值低位: PE 或 PB 处于历史序列 <30% 分位（.cache/valuation_{code}.csv）
  2. 趋势: ma20 > ma50 (UP 或 --)，排除下降趋势 DN
  3. 排除 ST/退市/PT
输出: 满足条件的股票，按距历史最低金额升序
"""

import io
import re
import ssl
import sys
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

CACHE_DIR = Path(".cache")
LINE_RE = re.compile(r"^(\d{6})\s+(.+?)\s+([\d.]+)\s+([\d.]+)\s+\+([\d.]+)元$")

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def fetch_sina(codes: list[str]) -> dict:
    """新浪批量行情（80只/批），返回 code -> (name, price)。停牌/退市股价格全 0。"""
    result: dict = {}
    for i in range(0, len(codes), 80):
        batch = codes[i : i + 80]
        items = []
        for c in batch:
            prefix = "sh" if c.startswith(("6", "9")) else ("bj" if c.startswith(("4", "8")) else "sz")
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
                    try:
                        price = float(p[3]) if len(p) > 3 else 0.0
                    except ValueError:
                        price = 0.0
                    result[code] = (p[0], price)
        except Exception:
            pass
    return result


def read_valuation(code: str) -> tuple[float | None, float | None]:
    """读估值历史分位 — PE/PB 当前值在历史序列中的百分位。"""
    vp = CACHE_DIR / f"valuation_{code}.csv"
    if not vp.exists():
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
                    # 只用正数序列 — 亏损(PE<0)或资不抵债(PB<0)无估值意义
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
    list_file = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    strict = len(sys.argv) > 2 and sys.argv[2] == "strict"
    if list_file is None or not list_file.exists():
        print("用法: python cli/near_low_screen.py <名单文件路径> [strict]")
        return

    entries: list[dict] = []
    for line in list_file.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_RE.match(line.strip())
        if m:
            code, name, price, low, above = m.groups()
            entries.append(
                {
                    "code": code,
                    "name": name.strip(),
                    "price": float(price),
                    "low": float(low),
                    "above": float(above),
                }
            )

    print(f"名单输入: {len(entries)} 只")

    passed: list[dict] = []
    no_val = no_trend = st_skip = 0
    up_n = sideways_n = 0

    for e in entries:
        name = e["name"]
        if "ST" in name or "退" in name or "PT" in name:
            st_skip += 1
            continue

        code = e["code"]
        pf = CACHE_DIR / f"prices_{code}.csv"
        if not pf.exists():
            continue
        try:
            df = pd.read_csv(pf, index_col=0, parse_dates=True)
            if len(df) < 60:
                continue
            close = df["close"]
            ma20 = float(close.rolling(20).mean().iloc[-1])
            ma50 = float(close.rolling(50).mean().iloc[-1])
            high_all = float(df["high"].max()) if "high" in df.columns else float(close.max())
        except Exception:
            continue

        if ma20 > ma50 * 1.01:
            trend = "UP"
            up_n += 1
        elif ma20 > ma50 * 0.99:
            trend = "--"
            sideways_n += 1
        else:
            no_trend += 1
            continue

        pe_pct, pb_pct = read_valuation(code)
        if pe_pct is None and pb_pct is None:
            no_val += 1
            continue
        from_high = high_all - e["price"]
        e["from_high"] = round(from_high, 2)

        if strict:
            cheap = (pe_pct is not None and pe_pct <= 20) or (pb_pct is not None and pb_pct <= 10)
            if trend != "UP" or not cheap:
                continue
        else:
            cheap = (pe_pct is not None and pe_pct < 30) or (pb_pct is not None and pb_pct < 30)
            if not cheap:
                continue

        e["trend"] = trend
        e["pe_pct"] = pe_pct
        e["pb_pct"] = pb_pct
        passed.append(e)

    passed.sort(key=lambda x: x["above"])

    if passed:
        rt = fetch_sina([e["code"] for e in passed])
        alive = [e for e in passed if rt.get(e["code"], (e["name"], None))[1] not in (None, 0.0)]
        if len(alive) < len(passed):
            print(f"停牌/退市剔除: {len(passed) - len(alive)} 只")
        passed = alive

    print(
        f"剔除ST/退市: {st_skip} | 趋势DN排除: {no_trend} | UP:{up_n} --:{sideways_n} "
        f"| 无估值缓存: {no_val} | 估值不低排除: {len(entries) - st_skip - no_trend - no_val - len(passed)}"
    )
    print(f"\n=== 同时满足 低估值(PE/PB<30%分位) + 趋势UP/-- 的股票: {len(passed)} 只 ===")
    print(f'{"代码":<8}{"名称":<10}{"现价":>7}{"高出":>7}  {"趋势":<4}{"PE%":>6}{"PB%":>6}  {"距高":>7}')
    for e in passed:
        pe_s = f"{e['pe_pct']:.0f}" if e["pe_pct"] is not None else "?"
        pb_s = f"{e['pb_pct']:.0f}" if e["pb_pct"] is not None else "?"
        fh_s = f"{e['from_high']:.1f}元" if "from_high" in e else "-"
        print(
            f"{e['code']:<8}{e['name']:<10}{e['price']:>7.2f}{e['above']:>+6.2f}元"
            f"  {e['trend']:<4}{pe_s:>5}%{pb_s:>5}%  {fh_s:>7}"
        )


if __name__ == "__main__":
    main()
