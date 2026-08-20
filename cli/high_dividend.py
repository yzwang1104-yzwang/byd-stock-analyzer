"""高分红股票扫描 — 按吉比特风格（一年多次分红、累计派息高）找同类。

口径: 最近12个月累计派息（每10股元）→ 换算每股派息 → 股息率 = 每股派息/现价
数据: akshare 巨潮分红明细(subprocess) + 新浪批量实时价
用法: python cli/high_dividend.py
"""

import io
import re
import ssl
import subprocess
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CODES = [
    "600519", "000858", "000568", "600809", "000596",  # 白酒
    "000895", "603156", "600887", "000333", "000651",  # 消费
    "601088", "601225", "600028", "601857", "600585",  # 能源周期
    "600036", "601006", "600660",                       # 金融/公用/制造
    "002555", "002517", "601928", "600373",             # 游戏传媒
]

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

INNER = """
import akshare as ak, sys
from datetime import datetime
cutoff = datetime(2025, 8, 1)
for c in sys.argv[1:]:
    try:
        df = ak.stock_dividend_cninfo(symbol=c)
        total = 0.0
        n = 0
        for _, r in df.iterrows():
            try:
                d = datetime.strptime(str(r['实施方案公告日期'])[:10], '%Y-%m-%d')
            except Exception:
                continue
            try:
                pay = float(r['派息比例'])
            except (TypeError, ValueError):
                continue
            if d >= cutoff and pay > 0:
                total += pay
                n += 1
        print(f"{c}|{total}|{n}")
    except Exception:
        print(f"{c}|ERR")
"""


def fetch_quotes() -> dict[str, tuple[str, float]]:
    """新浪批量行情，返回 code -> (name, price)。"""
    result: dict[str, tuple[str, float]] = {}
    for i in range(0, len(CODES), 80):
        batch = CODES[i : i + 80]
        items = [("sh" if c.startswith(("6", "9")) else "sz") + c for c in batch]
        try:
            url = f"https://hq.sinajs.cn/list={','.join(items)}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"},
            )
            raw = urllib.request.urlopen(req, timeout=10, context=_ssl_ctx).read()
            for line in raw.decode("gbk", errors="replace").split("\n"):
                m = re.search(r'hq_str_(?:sh|sz)(\d{6})="([^"]*)"', line)
                if m and m.group(2):
                    p = m.group(2).split(",")
                    try:
                        result[m.group(1)] = (p[0], float(p[3]))
                    except (ValueError, IndexError):
                        pass
        except Exception:
            pass
    return result


def main() -> None:
    result = subprocess.run(
        [sys.executable, "-c", INNER] + CODES,
        capture_output=True,
        text=True,
        timeout=600,
    )
    div_map: dict[str, tuple[float, int]] = {}
    for line in result.stdout.splitlines():
        parts = line.split("|")
        if len(parts) == 3 and parts[1] != "ERR":
            div_map[parts[0]] = (float(parts[1]), int(parts[2]))

    quotes = fetch_quotes()
    rows = []
    for code in CODES:
        if code not in div_map:
            continue
        total, n = div_map[code]
        name, price = quotes.get(code, ("?", 0.0))
        per_share = total / 10.0
        yld = per_share / price * 100 if price > 0 else 0.0
        rows.append((code, name, price, total, per_share, yld, n))

    rows.sort(key=lambda x: -x[5])
    print(f'{"代码":<8}{"名称":<8}{"现价":>8}{"12月累计派息":>13}{"每股派息":>9}{"股息率":>7}  次数')
    for code, name, price, total, per_share, yld, n in rows:
        print(f"{code:<8}{name:<8}{price:>8.2f}{total:>11.1f}元{per_share:>9.2f}{yld:>6.2f}%  {n}次")


if __name__ == "__main__":
    main()
