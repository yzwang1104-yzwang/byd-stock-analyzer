"""Django 视图——薄层，复用 core/ 模块。"""

import io, sys
import statistics
import json

from pathlib import Path

from django.shortcuts import render

def _get_stock_list() -> list[str]:
    """自动发现股票列表：持仓文件 + 缓存中有数据的股票。"""
    from pathlib import Path
    codes = set()
    # 从持仓文件读取
    pos_dir = Path(".position_history")
    if pos_dir.exists():
        for f in pos_dir.glob("*.json"):
            if f.stem != "portfolio_snapshots":
                codes.add(f.stem)
    # 从缓存读取有数据的股票
    cache_dir = Path(".cache")
    if cache_dir.exists():
        for f in cache_dir.glob("prices_*.csv"):
            codes.add(f.stem.replace("prices_", ""))
    # 排除 ETF，排序
    codes.discard("159915"); codes.discard("159919")
    codes.discard("510050"); codes.discard("510300"); codes.discard("512100")
    return sorted(codes)

STOCKS = _get_stock_list()

def _get_stock_name(code: str) -> str:
    """从腾讯API获取股票名称，失败返回代码。"""
    import urllib.request, ssl, os
    cache = {}
    name_file = ".cache/stock_names.json"
    # 读缓存
    if os.path.exists(name_file):
        try:
            cache = json.load(open(name_file, encoding="utf-8"))
        except: pass
    if code in cache:
        return cache[code]
    # 查腾讯API
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        prefix = "nq" if code.startswith(("9","8")) else ("sz" if code.startswith(("0","3")) else "sh")
        url = f"https://qt.gtimg.cn/q={prefix}{code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=5, context=ctx)
        text = resp.read().decode("gbk", errors="replace")
        for line in text.split("\n"):
            if "~" in line and "none_match" not in line:
                name = line.split("~")[1]
                cache[code] = name
                json.dump(cache, open(name_file, "w"))
                return name
    except Exception:
        pass
    return code


def _run_analysis(code: str) -> dict:
    """运行完整分析流水线，返回上下文 dict。"""
    old = sys.stdout
    sys.stdout = io.StringIO()
    try:
        from core.data_fetcher import fetch_normalized_data, fetch_valuation_data
        data = fetch_normalized_data(stock_code=code, force_refresh=False)

        from core.analyzers.technical import analyze as at
        result = at(data)

        try:
            valuation = fetch_valuation_data(stock_code=code)
        except Exception:
            valuation = None
        from core.analyzers.valuation import analyze as av
        result = av(result, valuation)

        from core.scoring import compute as cs
        sr = cs(result)

        from core.advice import generate as ga
        advice = ga(sr, result, current_price=data.latest_price)

        from core.market_context import get_market_regime, market_boost
        market = get_market_regime()
        advice.score = int(market_boost(advice.score, market))
        advice.score = min(100, max(0, advice.score))

        from core.buy_timing import calculate_path_to_buy
        timing = calculate_path_to_buy(
            advice.score, result.pe_percentile, result.pb_percentile,
            result.trend, data.latest_price, result.ma_20, result.ma_50
        )

        from core.prediction_tracker import get_calibration
        cal = get_calibration(code)

        from core.backtester import predict_direction
        dp = predict_direction(data.prices)
    finally:
        sys.stdout = old

    closes = [p.close for p in data.prices[-100:]]
    dates = [p.date.isoformat() for p in data.prices[-100:]]

    return {
        "code": code,
        "name": _get_stock_name(code),
        "price": data.latest_price,
        "score": advice.score,
        "action": advice.action_label,
        "action_class": advice.action,
        "rationale": advice.rationale,
        "position_pct": advice.position_pct,
        "confidence": advice.confidence,
        "pe_pct": result.pe_percentile,
        "pb_pct": result.pb_percentile,
        "rsi": result.rsi_14,
        "chg_20d": round((data.latest_price - (closes[-21] if len(closes) >= 21 else data.latest_price)) / (closes[-21] if len(closes) >= 21 else 1) * 100, 1) if len(closes) >= 21 else None,
        "trend": result.trend,
        "rsi": result.rsi_14,
        "macd": result.macd,
        "ma20": result.ma_20,
        "ma50": result.ma_50,
        "boll_upper": result.bollinger_upper,
        "boll_lower": result.bollinger_lower,
        "boll_mid": result.bollinger_middle,
        "atr": result.atr_14,
        "direction": dp["direction"],
        "dir_confidence": dp["confidence"],
        "dir_signals": dp["signals"][:3],
        "need_pts": timing["need_pts"],
        "timing_path": timing["paths"][0]["description"][:40] if timing["paths"] else "",
        "at_buy": timing["at_buy"],
        "dates": json.dumps(dates),
        "closes": json.dumps(closes),
        "ma20_series": json.dumps(_calc_sma(closes, 20)),
        "ma50_series": json.dumps(_calc_sma(closes, 50)),
        "boll_upper_series": json.dumps(_calc_boll(closes, 20, 2)[0]),
        "boll_lower_series": json.dumps(_calc_boll(closes, 20, 2)[2]),
        "cal_bias": cal.get("bias_correction", 0),
        "cal_range": cal.get("range_multiplier", 1),
    }


def _calc_sma(values: list, period: int) -> list:
    result = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(None)
        else:
            result.append(round(sum(values[i - period + 1 : i + 1]) / period, 2))
    return result


def _calc_boll(values: list, period: int, std: int) -> tuple:
    upper, mid, lower = [], [], []
    for i in range(len(values)):
        if i < period - 1:
            upper.append(None); mid.append(None); lower.append(None)
        else:
            window = values[i - period + 1 : i + 1]
            m = sum(window) / period
            s = statistics.stdev(window)
            upper.append(round(m + std * s, 2))
            mid.append(round(m, 2))
            lower.append(round(m - std * s, 2))
    return upper, mid, lower


# ====== Views ======

def dashboard(request):
    """仪表盘主页——持仓股票 + 比亚迪。"""
    from core.market_context import get_market_regime
    from core.position_manager import load_position
    market = get_market_regime()

    # 只显示有持仓的股票 + 比亚迪（始终关注）
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
            d = _run_analysis(code)
        except Exception as e:
            d = {"code": code, "name": code, "price": 0, "score": 0, "error": str(e)[:50]}
        stocks_data.append(d)

    # 按评分从高到低排序
    stocks_data.sort(key=lambda x: x.get("score", 0), reverse=True)

    from core.position_manager import load_position
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
    d = _run_analysis(code)
    return render(request, "stocks/detail.html", {"stock": d})


def stock_predict(request, code: str):
    """HTMX 局部刷新——单只股票的评分+预测。"""
    d = _run_analysis(code)
    return render(request, "stocks/_predict_panel.html", {"stock": d})


def scan(request):
    """多股票对比——按评分降序。"""
    stocks_data = []
    for c in STOCKS[:50]:  # 限制50只避免超时
        try:
            d = _run_analysis(c)
            stocks_data.append(d)
        except Exception:
            pass
    stocks_data.sort(key=lambda x: x.get("score", 0), reverse=True)
    # 转为JSON安全的格式（只保留展示字段，日期列表太大）
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
            d = _run_analysis(code)
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
