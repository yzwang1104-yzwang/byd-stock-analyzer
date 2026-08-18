"""持仓分析表 — 14 列固化格式（2026-07-28 定版）。

列: 代码/名称/股数/均价/现价/涨跌/市值/盈亏/盈%/最高/95%目标/需涨%/目标-均价/潜在利润
排序: 潜在利润降序（95% 目标价 × 股数 − 当前市值）
数据源: .position_history/ 持仓（排除已平仓）+ 腾讯实时行情 + .cache/ K线历史最高

usage:
    python cli/position_table.py
"""

import io
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# 直接运行 python cli/position_table.py 时 sys.path[0]=cli/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__" and sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

POSITION_DIR = ".position_history"
CACHE_DIR = ".cache"
SELL_TARGET_RATIO = 0.95   # 卖出目标 = 历史最高 × 95%（2026-07-17 由 70% 调整）

DISCLAIMER = "分析结果仅供参考，不构成任何投资建议。投资有风险，入市需谨慎。"


def load_positions() -> list[dict]:
    """从 .position_history/ 读取活跃持仓（排除已平仓持仓）。"""
    positions: list[dict] = []
    if not os.path.isdir(POSITION_DIR):
        return positions
    for fname in sorted(os.listdir(POSITION_DIR)):
        if not fname.endswith(".json") or fname == "portfolio_snapshots.json":
            continue
        code = fname.replace(".json", "")
        if len(code) != 6 or not code.isdigit():
            continue
        try:
            with open(os.path.join(POSITION_DIR, fname), encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries", [])
            total_shares = sum(e.get("shares", 0) for e in entries)
            total_cost = sum(e.get("price", 0) * e.get("shares", 0) for e in entries)
            net_adj = sum(a.get("amount", 0) for a in data.get("adjustments", []))
            if total_shares <= 0:
                continue  # 已平仓持仓，无仓位
            avg_price = (total_cost - net_adj) / total_shares
            positions.append({
                "code": code,
                "shares": total_shares,
                "avg_price": round(avg_price, 4),
            })
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return positions


def fetch_quotes(codes: list[str]) -> dict[str, dict]:
    """腾讯批量行情（每批最多 50 只，GBK 编码）。"""
    quotes: dict[str, dict] = {}
    for i in range(0, len(codes), 50):
        batch = codes[i:i + 50]
        symbols = ",".join(
            f"sh{c}" if c.startswith(("6", "9")) else f"sz{c}" for c in batch
        )
        url = f"https://qt.gtimg.cn/q={symbols}"
        try:
            text = urllib.request.urlopen(url, timeout=10).read().decode("gbk", errors="replace")
            for line in text.split(";"):
                line = line.strip()
                if "~" not in line:
                    continue
                parts = line.split("~")
                # parts[1]=名称 parts[2]=代码 parts[3]=现价 parts[32]=涨跌%
                if len(parts) > 32 and parts[2].isdigit():
                    quotes[parts[2]] = {
                        "name": parts[1],
                        "price": float(parts[3]),
                        "chg_pct": float(parts[32]),
                    }
        except Exception as e:
            print(f"  ⚠️ 行情获取失败: {e}")
    return quotes


def load_high_all(code: str) -> float | None:
    """从 K 线缓存读取历史最高价（无缓存返回 None）。"""
    path = os.path.join(CACHE_DIR, f"prices_{code}.csv")
    if not os.path.exists(path):
        return None
    try:
        import pandas as pd
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return float(df["high"].max()) if "high" in df.columns else None
    except Exception:
        return None


def main() -> None:
    """主入口：生成 14 列持仓表并按潜在利润降序输出。"""
    positions = load_positions()
    if not positions:
        print("无活跃持仓。")
        return

    quotes = fetch_quotes([p["code"] for p in positions])

    rows: list[dict] = []
    for p in positions:
        code = p["code"]
        q = quotes.get(code)
        if not q or q["price"] <= 0:
            continue
        price = q["price"]
        shares = p["shares"]
        avg = p["avg_price"]
        market_value = price * shares
        pnl = (price - avg) * shares
        pnl_pct = (price / avg - 1) * 100
        high = load_high_all(code)
        target = high * SELL_TARGET_RATIO if high else None
        to_target = (target / price - 1) * 100 if target else None
        gap = target - avg if target else None            # 目标-均价
        potential = gap * shares if gap is not None else None  # 潜在利润
        rows.append({
            "code": code, "name": q["name"], "shares": shares, "avg": avg,
            "price": price, "chg_pct": q["chg_pct"], "mv": market_value,
            "pnl": pnl, "pnl_pct": pnl_pct, "high": high, "target": target,
            "to_target": to_target, "gap": gap, "potential": potential,
        })

    # 潜在利润降序（无目标的排最后）
    rows.sort(key=lambda r: r["potential"] if r["potential"] is not None else -1e18)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print("=" * 118)
    print(f"  📊 持仓分析表 — {now}")
    print("=" * 118)

    hdr = (f"{'代码':<8} {'名称':<8} {'股数':>5} {'均价':>7} {'现价':>7} {'涨跌':>6} "
           f"{'市值':>9} {'盈亏':>8} {'盈%':>7} {'最高':>8} {'95%目标':>8} {'需涨%':>7} "
           f"{'目标-均价':>9} {'潜在利润':>9}")
    print(hdr)
    print("-" * 118)

    total_invest = 0.0
    total_mv = 0.0
    total_pnl = 0.0
    total_potential = 0.0

    def fmt(v: float | None, suffix: str = "") -> str:
        """可选值格式化：None 显示 —。"""
        return f"{v:,.2f}{suffix}" if v is not None else "—"

    for r in rows:
        total_invest += r["avg"] * r["shares"]
        total_mv += r["mv"]
        total_pnl += r["pnl"]
        if r["potential"] is not None:
            total_potential += r["potential"]

        print(f"{r['code']:<8} {r['name']:<8} {r['shares']:>5} {r['avg']:>7.2f} "
              f"{r['price']:>7.2f} {r['chg_pct']:>+6.2f}% {r['mv']:>9,.0f} "
              f"{r['pnl']:>+8.0f} {r['pnl_pct']:>+6.1f}% {fmt(r['high']):>8} "
              f"{fmt(r['target']):>8} {fmt(r['to_target'], '%'):>7} "
              f"{fmt(r['gap']):>9} {fmt(r['potential']):>9}")

    print("-" * 118)
    print(f"  总投入 {total_invest:,.0f} 元 | 总市值 {total_mv:,.0f} 元 "
          f"| 总盈亏 {total_pnl:+,.0f} 元 ({total_pnl / total_invest * 100:+.1f}%) "
          f"| 潜在利润空间 {total_potential:,.0f} 元")
    print(f"  共 {len(rows)} 只活跃持仓")
    print()
    print(f"  {DISCLAIMER}")


if __name__ == "__main__":
    main()
