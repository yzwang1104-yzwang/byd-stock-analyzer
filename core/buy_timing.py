"""买入时机精确计算——从当前评分反推需要什么条件才能触发买入。"""


def calculate_path_to_buy(
    current_score: int,
    pe_percentile: float | None,
    pb_percentile: float | None,
    trend: str,
    current_price: float,
    ma20: float | None = None,
    ma50: float | None = None,
) -> dict:
    """计算到达买入评分(70分)需要的条件变化。

    Returns:
        need_pts: 还差多少分
        paths: 可选的达标路径列表
        at_buy: 是否已可买入
    """
    need_pts = max(0, 70 - current_score)
    paths = []

    # 路径1: PE 回落
    if pe_percentile and pe_percentile > 30 and current_price > 0:
        pe_drop = need_pts / (0.35 * 10) * 10
        target_pe_pct = max(5, pe_percentile - pe_drop)
        if target_pe_pct < pe_percentile:
            target_price = round(current_price * (target_pe_pct / pe_percentile), 2)
            paths.append({
                "type": "PE回落",
                "description": f"市盈率分位从 {pe_percentile:.0f}% 降至 {target_pe_pct:.0f}%",
                "price_target": target_price,
                "effort": "等待回调" if trend == "down" else "需要主动下跌",
            })

    # 路径2: 趋势反转
    if trend in ("down", "sideways_down"):
        boost = 14  # 趋势从 down→up 约提升14分（20%权重 × 70分差）
        paths.append({
            "type": "趋势反转",
            "description": f"MA20 站上 MA50（均线金叉）",
            "price_target": round(ma50, 2) if ma50 else None,
            "effort": "等待金叉信号",
            "score_boost": boost,
        })

    # 路径3: 综合改善
    if pe_percentile and pe_percentile > 40 and trend in ("down", "sideways_down", "sideways_up"):
        target = max(25, pe_percentile - 20)
        paths.append({
            "type": "综合改善",
            "description": f"市盈率分位降至 {target:.0f}% + 趋势翻转为 up",
            "price_target": round(current_price * (target / pe_percentile), 2) if pe_percentile > 0 else None,
            "effort": "最可能自然达标的路径",
        })

    return {
        "need_pts": need_pts,
        "current_score": current_score,
        "target_score": 70,
        "paths": paths,
        "at_buy": current_score >= 70,
    }
