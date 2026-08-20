"""批量回填估值缓存 — 为名单中缺少 valuation_*.csv 的股票拉取 PE/PB 历史。

数据源: akshare stock_zh_valuation_baidu（百度估值，近一年）
缓存格式: 与 core/data_fetcher.fetch_valuation_data 一致
用法: python cli/backfill_valuation.py <名单文件路径>
"""

import csv
import io
import re
import sys
import time
from datetime import date
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import akshare as ak

CACHE_DIR = Path(".cache")
LINE_RE = re.compile(r"^(\d{6})\s+(.+?)\s+([\d.]+)\s+([\d.]+)\s+\+([\d.]+)元$")
FIELDNAMES = ["date", "current_pe", "current_pb", "industry_pe", "industry_pb", "pe_history", "pb_history"]


def fetch_indicator(code: str, indicator: str) -> list[float]:
    """拉取单指标近一年序列，失败重试 1 次。"""
    for attempt in range(2):
        try:
            df = ak.stock_zh_valuation_baidu(symbol=code, indicator=indicator, period="近一年")
            if df is not None and not df.empty:
                return [float(x) for x in df["value"].dropna().tolist()]
        except Exception:
            if attempt == 1:
                return []
            time.sleep(0.5)
    return []


def main() -> None:
    list_file = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if list_file is None or not list_file.exists():
        print("用法: python cli/backfill_valuation.py <名单文件路径>")
        return

    codes: list[str] = []
    for line in list_file.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_RE.match(line.strip())
        if m:
            codes.append(m.group(1))

    todo = [c for c in codes if not (CACHE_DIR / f"valuation_{c}.csv").exists()]
    print(f"名单 {len(codes)} 只 | 缺估值缓存: {len(todo)} 只", flush=True)

    ok = fail = 0
    for i, code in enumerate(todo, 1):
        pe_hist = fetch_indicator(code, "市盈率(TTM)")
        pb_hist = fetch_indicator(code, "市净率")
        time.sleep(0.25)

        if not pe_hist and not pb_hist:
            fail += 1
        else:
            row = {
                "date": date.today().isoformat(),
                "current_pe": str(pe_hist[-1]) if pe_hist else "",
                "current_pb": str(pb_hist[-1]) if pb_hist else "",
                "industry_pe": "",
                "industry_pb": "",
                "pe_history": "|".join(str(x) for x in pe_hist[-252:]),
                "pb_history": "|".join(str(x) for x in pb_hist[-252:]),
            }
            with open(CACHE_DIR / f"valuation_{code}.csv", "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()
                writer.writerow(row)
            ok += 1

        if i % 20 == 0:
            print(f"  进度 {i}/{len(todo)} | 成功 {ok} | 失败 {fail}", flush=True)

    print(f"完成: 成功 {ok} | 失败 {fail}")


if __name__ == "__main__":
    main()
