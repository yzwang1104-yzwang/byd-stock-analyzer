"""利润提醒 — 持仓浮动盈亏达到目标金额时提醒卖出。

目标配置: PROFIT_TARGETS = {股票代码: 目标利润(元)}
2026-08-18 用户设置: 山西焦煤(000983) 利润 120 元、万憬能源(002700) 利润 280 元时提醒卖出。

数据源: 腾讯实时行情 + 持仓记录(唯一数据源 .position_history/)

usage:
    python cli/profit_alert.py
"""

import io
import logging
import sys
from datetime import datetime
from pathlib import Path

# 直接运行 python cli/profit_alert.py 时 sys.path[0]=cli/，core 包找不到
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows UTF-8 编码（仅直接运行时，不影响 pytest 的 stdout capture）
if __name__ == "__main__" and sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from core.data_fetcher import fetch_realtime_quote
from core.position_manager import load_position

logger = logging.getLogger(__name__)

# ====== 利润目标配置 ======
PROFIT_TARGETS: dict[str, float] = {
    "000983": 120.0,   # 山西焦煤: 100股 均价6.30 → 股价7.50元时达标
    "002700": 280.0,   # 万憬能源: 100股 均价5.23 → 股价8.03元时达标
}

DISCLAIMER = "分析结果仅供参考，不构成任何投资建议。投资有风险，入市需谨慎。"


def check_targets() -> list[dict]:
    """检查所有目标持仓的当前利润。

    Returns:
        list[dict]: 每只股票的利润明细，含 reached 是否达标字段。
    """
    results: list[dict] = []
    for code, target_profit in PROFIT_TARGETS.items():
        pos = load_position(code)
        if pos is None or pos.total_shares <= 0:
            logger.warning("目标持仓不存在或已平仓: %s", code)
            continue
        try:
            quote = fetch_realtime_quote(code)
            cur = float(quote.get("f43", 0)) / 100  # 腾讯格式：价格×100
        except Exception as e:
            logger.warning("实时行情获取失败 %s: %s", code, e)
            continue
        profit = (cur - pos.avg_cost) * pos.total_shares
        results.append({
            "code": code,
            "name": quote.get("f57") or code,
            "cur": cur,
            "avg_cost": pos.avg_cost,
            "shares": pos.total_shares,
            "profit": profit,
            "target": target_profit,
            "reached": profit >= target_profit,
        })
    return results


def main() -> None:
    """主入口：扫描利润目标，达标输出卖出提醒。"""
    now = datetime.now()
    print(f"=== 利润提醒扫描 === {now.strftime('%Y-%m-%d %H:%M')}")
    print()

    results = check_targets()
    reached = [r for r in results if r["reached"]]
    pending = [r for r in results if not r["reached"]]

    for r in reached:
        print(f"  ⚡ 卖出提醒: {r['code']} {r['name']} 利润 {r['profit']:+.0f} 元 "
              f"≥ 目标 {r['target']:.0f} 元")
        print(f"     现价 {r['cur']:.2f} | 均价 {r['avg_cost']:.2f} "
              f"| 持仓 {r['shares']} 股 | 建议卖出落袋为安")
        print()

    if not reached:
        print("  本次扫描无达标持仓。当前进度：")
        print()
        print(f"  {'代码':<8} {'名称':<10} {'现价':>7} {'均价':>7} "
              f"{'当前利润':>9} {'目标利润':>9} {'进度':>7}")
        for r in pending:
            pct = r["profit"] / r["target"] * 100 if r["target"] > 0 else 0
            print(f"  {r['code']:<8} {r['name']:<10} {r['cur']:>7.2f} {r['avg_cost']:>7.2f} "
                  f"{r['profit']:>+8.0f}元 {r['target']:>8.0f}元 {pct:>6.0f}%")
        print()

    print(f"  {DISCLAIMER}")


if __name__ == "__main__":
    main()
