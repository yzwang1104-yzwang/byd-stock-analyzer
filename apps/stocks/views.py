"""Django 视图——薄层，只做请求分发和响应渲染。业务逻辑在 services.py。

红线 #15: View 不放业务逻辑。
"""

import json
from pathlib import Path

from django.shortcuts import render

from apps.stocks.services import get_stock_list, run_analysis

STOCKS = get_stock_list()


# ====== Views（薄层——无业务逻辑） ======

def dashboard(request):
    """仪表盘主页——持仓股票 + 比亚迪。"""
    from core.market_context import get_market_regime
    from core.position_manager import load_position
    market = get_market_regime()

    has_pos = set()
    pos_dir = Path(".position_history")
    if pos_dir.exists():
        for f in pos_dir.glob("*.json"):
            if f.stem != "portfolio_snapshots":
                has_pos.add(f.stem)
    show_codes = list(has_pos) if has_pos else ["002594", "600104", "600370"]
    if "002594" not in show_codes:
        show_codes.insert(0, "002594")

    stocks_data = []
    for code in show_codes:
        try:
            stocks_data.append(run_analysis(code))
        except Exception as e:
            stocks_data.append({"code": code, "name": code, "price": 0, "score": 0, "error": str(e)[:50]})
    stocks_data.sort(key=lambda x: x.get("score", 0), reverse=True)

    for d in stocks_data:
        pos = load_position(d["code"])
        if pos:
            pnl = pos.unrealized_pnl(d.get("price", 0))
            d["has_position"] = True
            d["pos_shares"] = pos.total_shares
            d["pos_avg"] = pos.avg_cost
            d["pos_pnl_pct"] = pnl["pnl_pct"]
            d["pos_trigger_add"] = pos.can_add and d.get("price", 0) <= pos.next_add_price
            d["pos_next_add"] = pos.next_add_price
        else:
            d["has_position"] = False

    stocks_json = json.dumps([
        {k: v for k, v in d.items() if k not in ("dates", "closes", "ma20_series", "ma50_series", "boll_upper_series", "boll_lower_series")}
        for d in stocks_data
    ], ensure_ascii=False)
    return render(request, "stocks/dashboard.html", {
        "stocks": stocks_data,
        "stocks_json": stocks_json,
        "market": market,
    })


def stock_detail(request, code: str):
    """单只股票详情——K线图 + 完整分析。"""
    d = run_analysis(code)
    return render(request, "stocks/detail.html", {"stock": d})


def stock_predict(request, code: str):
    """HTMX 局部刷新——单只股票的评分+预测。"""
    d = run_analysis(code)
    return render(request, "stocks/_predict_panel.html", {"stock": d})


def scan(request):
    """多股票对比——按评分降序。"""
    stocks_data = []
    for c in STOCKS[:50]:
        try:
            stocks_data.append(run_analysis(c))
        except Exception:
            pass
    stocks_data.sort(key=lambda x: x.get("score", 0), reverse=True)
    stocks_json = json.dumps([
        {k: v for k, v in d.items() if k not in ("dates", "closes", "ma20_series", "ma50_series", "boll_upper_series", "boll_lower_series")}
        for d in stocks_data
    ], ensure_ascii=False)
    return render(request, "stocks/scan.html", {"stocks": stocks_data, "stocks_json": stocks_json})


def positions(request):
    """持仓管理页面。"""
    from core.position_manager import load_position
    pos_list = []
    for code in STOCKS:
        pos = load_position(code)
        if pos:
            d = run_analysis(code)
            pnl = pos.unrealized_pnl(d["price"])
            pos_list.append({
                **d,
                "has_position": True,
                "pos_shares": pos.total_shares,
                "pos_avg": pos.avg_cost,
                "pos_cost": pos.total_cost,
                "pos_pnl": pnl["pnl"],
                "pos_pnl_pct": pnl["pnl_pct"],
                "pos_entries": pos.entries,
                "pos_next_add": pos.next_add_price,
                "pos_adds_left": pos.adds_remaining,
                "pos_trigger_add": pos.can_add and d["price"] <= pos.next_add_price,
            })
    total_pnl = sum(p["pos_pnl"] for p in pos_list)
    total_cost = sum(p["pos_cost"] for p in pos_list)
    pos_json = json.dumps([
        {k: v for k, v in p.items() if k not in ("dates", "closes", "ma20_series", "ma50_series", "boll_upper_series", "boll_lower_series", "pos_entries")}
        for p in pos_list
    ], ensure_ascii=False)
    return render(request, "stocks/positions.html", {
        "positions": pos_list,
        "positions_json": pos_json,
        "total_pnl": total_pnl,
        "total_cost": total_cost,
        "total_pnl_pct": (total_pnl / total_cost * 100) if total_cost > 0 else 0,
    })
