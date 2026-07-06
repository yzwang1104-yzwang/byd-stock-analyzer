"""卖出提醒 — 低点买入持仓在价格回弹至历史最高 45%-70% 时告警。

触发条件（必须同时满足）：
  1. 低点买入：持仓均价 ≤ 历史最低价 × 1.15
  2. 目标区间：high_all × 45% ≤ 当前实时价 ≤ high_all × 70%

数据源：腾讯实时行情 + 腾讯 K 线全量（每次重新拉取，不做缓存）

usage:
    python cli/sell_alert.py
"""

import io
import os
import sys
from datetime import datetime

# Windows UTF-8 编码（仅直接运行时，不影响 pytest 的 stdout capture）
if __name__ == "__main__" and sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from core.data_fetcher import fetch_normalized_data, fetch_realtime_quote
from core.position_manager import load_position, POSITION_FILE

# ====== 阈值配置 ======
LOW_BUY_THRESHOLD = 1.15   # 买入均价 ≤ 历史最低 × 1.15 视为低点买入
SELL_LOWER = 0.45          # 目标区间下边界：历史最高 × 45%
SELL_UPPER = 0.70          # 目标区间上边界：历史最高 × 70%

DISCLAIMER = "分析结果仅供参考，不构成任何投资建议。投资有风险，入市需谨慎。"

# 股票名称映射（从 buy_alert.py 复用的已知名称表 + akshare 实时获取）
# 注：akshare.stock_info_a_code_name() 在某些环境下 segfault，
#     因此放在子进程中执行，崩溃不影响主进程。
NAMES: dict[str, str] = {}
try:
    import subprocess
    _script = (
        "import akshare; df = akshare.stock_info_a_code_name(); "
        "print('\\n'.join(f\"{r['code']}|{r['name']}\" for _, r in df.iterrows()))"
    )
    _r = subprocess.run(
        [sys.executable, "-c", _script],
        capture_output=True, text=True, timeout=60,
    )
    if _r.returncode == 0:
        for _line in _r.stdout.strip().split("\n"):
            if "|" in _line:
                _c, _n = _line.split("|", 1)
                NAMES[_c] = _n
except Exception:
    pass

KNOWN: dict[str, str] = {
    "000001": "平安银行", "000002": "万科A", "000568": "泸州老窖",
    "000596": "古井贡酒", "000625": "长安汽车", "000690": "宝新能源",
    "000858": "五粮液", "002304": "洋河股份", "002352": "顺丰控股",
    "002459": "晶澳科技", "002469": "三维化学", "002594": "比亚迪",
    "002855": "捷荣技术", "002920": "德赛西威", "300122": "智飞生物",
    "300498": "温氏股份", "300529": "健帆生物", "300760": "迈瑞医疗",
    "600048": "保利发展", "600085": "同仁堂", "600104": "上汽集团",
    "600370": "*ST三房", "600436": "片仔癀", "600438": "通威股份",
    "600567": "山鹰国际", "600585": "海螺水泥", "600720": "中交设计",
    "600795": "国电电力", "600809": "山西汾酒", "600845": "宝信软件",
    "600887": "伊利股份", "601012": "隆基绿能", "601238": "广汽集团",
    "603395": "红四方", "603833": "欧派家居", "688036": "传音控股",
    "688169": "石头科技", "688223": "晶科能源", "688271": "联影医疗",
    "920802": "保丽洁",
}
for k, v in KNOWN.items():
    if k not in NAMES:
        NAMES[k] = v


def _get_name(code: str) -> str:
    """获取股票名称。"""
    return NAMES.get(code, "???")


def _sort_key(r: dict) -> tuple:
    """排序键：已触发排最前，然后按距区间从小到大。"""
    if r["in_range"]:
        return (0, 0)
    if r["dist"].startswith("↓"):
        return (0, float(r["dist"].strip("↓%")) + 0.01)
    return (1, float(r["dist"].strip("↑%")))


def main() -> None:
    """主入口：扫描所有持仓，判断卖出提醒条件，输出表格。"""
    now = datetime.now()
    print(f"=== 卖出提醒扫描 === {now.strftime('%Y-%m-%d %H:%M')}")
    print()
    print("  低点买入持仓 → 接近最高点 45%-70% 出仓区间")
    print()

    # ── 扫描持仓目录 ──
    if not POSITION_FILE.exists():
        print("  无持仓记录。")
        print()
        _print_footer(now, 0, 0, 0)
        return

    position_files = sorted(
        f for f in os.listdir(POSITION_FILE)
        if f.endswith(".json") and f != "portfolio_snapshots.json"
    )

    if not position_files:
        print("  无持仓记录。")
        print()
        _print_footer(now, 0, 0, 0)
        return

    results: list[dict] = []
    low_buy_count = 0
    skipped: list[dict] = []   # 不符合条件的持仓及原因

    for fname in position_files:
        code = fname.replace(".json", "")
        pos = load_position(code)
        if pos is None or pos.total_shares == 0:
            continue

        avg_cost = pos.avg_cost

        # ── 数据获取：实时行情 + 全量K线（force_refresh，不走缓存） ──
        try:
            quote = fetch_realtime_quote(code)
            cur = float(quote.get("f43", 0)) / 100  # 腾讯格式：价格×100
            if cur <= 0:
                skipped.append({
                    "code": code, "name": _get_name(code),
                    "avg_cost": avg_cost, "reason": "实时行情不可用",
                })
                continue
        except Exception:
            skipped.append({
                "code": code, "name": _get_name(code),
                "avg_cost": avg_cost, "reason": "实时行情获取失败",
            })
            continue

        try:
            data = fetch_normalized_data(stock_code=code, force_refresh=True)
            if not data.prices or len(data.prices) < 50:
                skipped.append({
                    "code": code, "name": _get_name(code),
                    "avg_cost": avg_cost, "reason": f"K线数据不足({len(data.prices)}条)",
                })
                continue
            high_all = max(p.high for p in data.prices)
            low_all = min(p.low for p in data.prices)
        except Exception:
            skipped.append({
                "code": code, "name": _get_name(code),
                "avg_cost": avg_cost, "reason": "K线数据获取失败",
            })
            continue

        # ── 条件 1：低点买入判断 ──
        is_low_buy = avg_cost <= low_all * LOW_BUY_THRESHOLD

        # ── 条件 2：目标区间判断 ──
        target_low = high_all * SELL_LOWER
        target_high = high_all * SELL_UPPER
        in_range = target_low <= cur <= target_high

        if in_range:
            dist = "已触发"
        elif cur < target_low:
            gap_pct = (target_low / cur - 1) * 100
            dist = f"↓{gap_pct:.0f}%"
        else:
            gap_pct = (cur / target_high - 1) * 100
            dist = f"↑{gap_pct:.0f}%"

        pnl_pct = (cur / avg_cost - 1) * 100

        result = {
            "code": code,
            "name": _get_name(code),
            "cur": cur,
            "avg_cost": avg_cost,
            "high_all": high_all,
            "low_all": low_all,
            "target_low": target_low,
            "target_high": target_high,
            "dist": dist,
            "pnl_pct": pnl_pct,
            "in_range": in_range,
            "is_low_buy": is_low_buy,
        }
        if is_low_buy:
            low_buy_count += 1
            results.append(result)
        else:
            from_low_pct = (avg_cost / low_all - 1) * 100
            skipped.append({
                "code": code, "name": _get_name(code),
                "avg_cost": avg_cost, "reason": f"买入价高于历史最低{from_low_pct:.0f}%",
            })

    # ── 排序：已触发排最前，然后按距区间从小到大 ──
    results.sort(key=_sort_key)

    # ── 输出表格 ──
    triggered = [r for r in results if r["in_range"]]

    if not results:
        print("  无符合低点买入条件的持仓。")
        print()
        if skipped:
            print("  不符合条件原因：")
            for s in skipped:
                print(f"    {s['code']} {s['name']}: {s['reason']}")
        _print_footer(now, 0, len(position_files), low_buy_count)
        return

    print(f"{'#':>3}  {'代码':<8} {'名称':<8} {'现价':>7} {'均价':>7} "
          f"{'历史最高':>9} {'目标区间':>16} {'距区间':>6} {'盈亏':>6}")
    print("──  " + "─" * 95)

    for i, r in enumerate(results, 1):
        tag = "⚡" if r["in_range"] else "  "
        target_range = f"{r['target_low']:.2f}~{r['target_high']:.2f}"
        print(f"{i:>3}  {r['code']:<8} {r['name']:<8} {r['cur']:>7.2f} {r['avg_cost']:>7.2f} "
              f"{r['high_all']:>9.2f} {target_range:>16} {r['dist']:>6} {r['pnl_pct']:>+5.1f}%")

    print("──  " + "─" * 95)
    print()

    _print_footer(now, len(triggered), len(position_files), low_buy_count)

    # ── 触发告警 ──
    for r in triggered:
        from_low_pct = (r["avg_cost"] / r["low_all"] - 1) * 100
        print(f"  ⚡ {r['code']} {r['name']}：当前 {r['cur']:.2f} "
              f"已进入目标区间 {r['target_low']:.2f}~{r['target_high']:.2f}")
        print(f"     买入均价 {r['avg_cost']:.2f}"
              f"（距历史最低 +{from_low_pct:.1f}%） → 可考虑出仓")
        print()

    if not triggered:
        print("  本次无触发。")
        print()

    print(f"  {DISCLAIMER}")


def _print_footer(scan_time: datetime, triggered: int, total_positions: int, low_buy: int) -> None:
    """打印底部汇总信息。"""
    print(f"── 触发 {triggered} 只 | 扫描 {total_positions} 只持仓"
          f" | {low_buy} 只符合低点买入条件")
    print(f"── 数据: 腾讯实时行情 + 全量K线 | 刷新时间: {scan_time.strftime('%H:%M:%S')}")
    print()


if __name__ == "__main__":
    main()
