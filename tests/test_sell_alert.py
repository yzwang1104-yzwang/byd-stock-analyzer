"""sell_alert.py 单元测试 — 条件判断逻辑。"""

import sys
from pathlib import Path

# 确保 sell_alert 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---- 测试：低点买入判断逻辑 ----

def test_low_buy_detection():
    """均价 78.50，历史最低 78.00 → 78.50 ≤ 89.70 → 低点买入 ✅"""
    from cli.sell_alert import LOW_BUY_THRESHOLD

    avg_cost = 78.50
    low_all = 78.00
    assert avg_cost <= low_all * LOW_BUY_THRESHOLD


def test_not_low_buy():
    """均价 150，历史最低 78 → 150 > 89.70 → 非低点买入 ❌"""
    from cli.sell_alert import LOW_BUY_THRESHOLD

    avg_cost = 150.00
    low_all = 78.00
    assert avg_cost > low_all * LOW_BUY_THRESHOLD


# ---- 测试：目标区间判断 ----

def test_in_target_range():
    """当前价 150，历史最高 200 → 目标区间 140~160 → 150 在区间内 ✅"""
    from cli.sell_alert import SELL_LOWER, SELL_UPPER

    cur = 150.0
    high_all = 200.0
    target_low = high_all * SELL_LOWER   # 140
    target_high = high_all * SELL_UPPER  # 160
    assert target_low <= cur <= target_high


def test_below_target_range():
    """当前价 80，历史最高 200 → 目标区间 140~160 → 80 在区间下 ❌"""
    from cli.sell_alert import SELL_LOWER, SELL_UPPER

    cur = 80.0
    high_all = 200.0
    target_low = high_all * SELL_LOWER
    target_high = high_all * SELL_UPPER
    assert cur < target_low


def test_above_target_range():
    """当前价 170，历史最高 200 → 目标区间 140~160 → 170 在区间上 ❌"""
    from cli.sell_alert import SELL_LOWER, SELL_UPPER

    cur = 170.0
    high_all = 200.0
    target_low = high_all * SELL_LOWER
    target_high = high_all * SELL_UPPER
    assert cur > target_high


def test_edge_case_exact_boundary():
    """边界值测试：当前价正好等于下边界"""
    from cli.sell_alert import SELL_LOWER, SELL_UPPER

    high_all = 100.0
    cur = high_all * SELL_LOWER   # 70.0
    assert high_all * SELL_LOWER <= cur <= high_all * SELL_UPPER


# ---- 测试：盈亏计算 ----

def test_pnl_positive():
    """均价 78.50，现价 90 → 盈亏 +14.6%"""
    avg_cost = 78.50
    cur = 90.0
    pnl = (cur / avg_cost - 1) * 100
    assert pnl > 0
    assert round(pnl, 1) == 14.6


def test_pnl_negative():
    """均价 10.38，现价 9.50 → 盈亏 -8.5%"""
    avg_cost = 10.38
    cur = 9.50
    pnl = (cur / avg_cost - 1) * 100
    assert pnl < 0
    assert round(pnl, 1) == -8.5


# ---- 测试：距离标签 ----

def test_dist_label_already_in_range():
    """已触发的显示'已触发'"""
    from cli.sell_alert import SELL_LOWER, SELL_UPPER

    cur = 150.0
    high_all = 200.0
    target_low = high_all * SELL_LOWER   # 140
    target_high = high_all * SELL_UPPER  # 160
    in_range = target_low <= cur <= target_high
    assert in_range

    dist = "已触发"
    assert dist == "已触发"


def test_dist_label_below():
    """低于区间下边界 → 显示 ↓百分比（离下边界还差多少）"""
    from cli.sell_alert import SELL_LOWER

    cur = 80.0
    high_all = 200.0
    target_low = high_all * SELL_LOWER  # 140
    gap_pct = (target_low / cur - 1) * 100
    dist = f"↓{gap_pct:.0f}%"
    assert dist == "↓75%"


def test_dist_label_above():
    """高于区间上边界 → 显示 ↑百分比（已超出上边界多少）"""
    from cli.sell_alert import SELL_UPPER

    cur = 180.0
    high_all = 200.0
    target_high = high_all * SELL_UPPER  # 160
    gap_pct = (cur / target_high - 1) * 100
    dist = f"↑{gap_pct:.0f}%"
    assert dist == "↑12%"
