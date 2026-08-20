"""查询股票最新股息率 — akshare 分红明细 + 新浪实时价。

股息率 = 最近一次实施分红每10股派息 / 10 / 现价 × 100%
akshare 走 subprocess 避免 segfault；分红明细列序: 公告日期,送股,转增,派息,进度,除权除息日,股权登记日,红利发放日
"""

import io
import re
import ssl
import subprocess
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CODES = [
    "603589", "601595", "600845", "605108", "601633", "000550", "002557",
    "000786", "603000", "002984", "600161", "600754", "603927", "002423",
    "002670", "600559", "000555", "601136", "002777", "002103", "600315",
    "605050", "600765", "600104", "002572",
]

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

INNER = """
import akshare as ak, sys
for c in sys.argv[1:]:
    try:
        df = ak.stock_history_dividend_detail(symbol=c, indicator='分红')
        for _, r in df.iterrows():
            try:
                pay = float(r.iloc[3])
            except (TypeError, ValueError):
                continue
            if pay > 0:
                print(f"{c}|{pay}|{r.iloc[0]}")
                break
        else:
            print(f"{c}|NONE")
    except Exception:
        print(f"{c}|ERR")
"""


def fetch_prices() -> dict[str, float]:
    """新浪批量实时价，返回 code -> price。"""
    result: dict[str, float] = {}
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
                        result[m.group(1)] = float(p[3])
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
    pay_map: dict[str, float] = {}
    date_map: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split("|")
        if len(parts) == 3 and parts[1] != "ERR" and parts[1] != "NONE":
            pay_map[parts[0]] = float(parts[1])
            date_map[parts[0]] = parts[2]

    prices = fetch_prices()
    rows = []
    for code in CODES:
        if code not in pay_map:
            rows.append((code, 0.0, 0.0, prices.get(code, 0.0), "无分红"))
            continue
        price = prices.get(code, 0.0)
        per_share = pay_map[code] / 10.0
        yld = per_share / price * 100 if price > 0 else 0.0
        rows.append((code, per_share, yld, price, date_map[code]))

    rows.sort(key=lambda x: -x[2])
    print(f'{"代码":<8}{"名称":<10}{"现价":>7}{"每股派息":>9}{"股息率":>7}  公告日期')
    for code, per_share, yld, price, d in rows:
        name = NAMES.get(code, "?")
        print(f"{code:<8}{name:<10}{price:>7.2f}{per_share:>9.2f}{yld:>6.2f}%  {d}")


NAMES = {
    "603589": "口子窖", "601595": "上海电影", "600845": "宝信软件",
    "605108": "同庆楼", "601633": "长城汽车", "000550": "江铃汽车",
    "002557": "洽洽食品", "000786": "北新建材", "603000": "人民网",
    "002984": "森麒麟", "600161": "天坛生物", "600754": "锦江酒店",
    "603927": "中科软", "002423": "中粮资本", "002670": "国盛证券",
    "600559": "老白干酒", "000555": "神州信息", "601136": "首创证券",
    "002777": "久远银海", "002103": "广博股份", "600315": "上海家化",
    "605050": "福然德", "600765": "中航重机", "600104": "上汽集团",
    "002572": "索菲亚",
}

if __name__ == "__main__":
    main()
