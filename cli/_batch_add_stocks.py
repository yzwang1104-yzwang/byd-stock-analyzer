"""批量新增股票到缓存池。"""

import csv
import os
import sys
import io
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from core.data_fetcher import fetch_normalized_data, _cache_path


def main():
    if not os.path.exists(".cache/_new_stocks.txt"):
        print("未找到 _new_stocks.txt")
        return

    with open(".cache/_new_stocks.txt", encoding="utf-8") as f:
        stocks = [line.strip().split(",")[0] for line in f if line.strip()]

    print(f"开始新增 {len(stocks)} 只股票...")
    ok = 0
    fail = 0
    t0 = time.time()

    for i, code in enumerate(stocks):
        try:
            data = fetch_normalized_data(code, force_refresh=True)
            if data and data.prices and len(data.prices) >= 50:
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            print(f"  {i+1}/{len(stocks)}  OK:{ok} FAIL:{fail}  {elapsed:.0f}s")

    elapsed = time.time() - t0
    print(f"完成: {ok}成功 {fail}失败  耗时:{elapsed:.0f}s")

    # Count current total
    total = sum(1 for f in os.listdir(".cache") if f.startswith("prices_"))
    print(f"缓存池总量: {total} 只")


if __name__ == "__main__":
    main()
