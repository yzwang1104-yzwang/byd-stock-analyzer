"""批量回填价格缓存 — 补齐全市场A股缺失的 prices_*.csv。

数据源: 腾讯 fqkline 前复权全历史日线（2000根上限）
缓存格式: date,open,high,low,close,volume（与 core/data_fetcher 一致）
用法: python cli/backfill_prices.py
"""

import csv
import io
import json
import os
import ssl
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import akshare as ak

CACHE_DIR = ".cache"

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def fetch_kline(code: str) -> list[list]:
    """腾讯前复权全历史日线，返回 [date, open, close, high, low, volume] 行列表。"""
    prefix = "nq" if code.startswith(("4", "8", "92")) else ("sh" if code.startswith(("6", "9")) else "sz")
    try:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,2000,qfq"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=15, context=_ssl_ctx).read().decode("utf-8", "replace")
        data = json.loads(raw)
        days = data["data"][f"{prefix}{code}"].get("qfqday") or data["data"][f"{prefix}{code}"].get("day")
        return days or []
    except Exception:
        return []


def fetch_kline_sina(code: str) -> list[list]:
    """新浪日线（不复权，1023根）— 腾讯限流时的降级源。

    返回 [date, open, close, high, low, volume] 行（与腾讯同序，方便共用写缓存逻辑）。
    """
    prefix = "bj" if code.startswith(("4", "8", "92")) else ("sh" if code.startswith(("6", "9")) else "sz")
    try:
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen=1023"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=15, context=_ssl_ctx).read().decode("utf-8", "replace")
        bars = json.loads(raw)
        if not isinstance(bars, list):
            return []
        return [
            [b["day"], b["open"], b["close"], b["high"], b["low"], b["volume"]]
            for b in bars
        ]
    except Exception:
        return []


def main() -> None:
    all_df = ak.stock_info_a_code_name()
    all_codes = set(all_df["code"].tolist())
    existing = {f.replace("prices_", "").replace(".csv", "") for f in os.listdir(CACHE_DIR) if f.startswith("prices_")}
    todo = sorted(all_codes - existing)
    print(f"全市场: {len(all_codes)} 只 | 缓存已有: {len(existing)} | 待回填: {len(todo)} 只", flush=True)

    ok = fail = 0
    for i, code in enumerate(todo, 1):
        days = fetch_kline(code) or fetch_kline_sina(code)
        if not days:
            time.sleep(1)
            days = fetch_kline(code) or fetch_kline_sina(code)
        time.sleep(0.4)
        if not days:
            fail += 1
        else:
            path = os.path.join(CACHE_DIR, f"prices_{code}.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "open", "high", "low", "close", "volume"])
                for d in days:
                    # 腾讯格式: [date, open, close, high, low, volume]
                    writer.writerow([d[0], d[1], d[3], d[4], d[2], d[5]])
            ok += 1

        if i % 100 == 0:
            print(f"  进度 {i}/{len(todo)} | 成功 {ok} | 失败 {fail}", flush=True)

    print(f"完成: 成功 {ok} | 失败 {fail}")


if __name__ == "__main__":
    main()
