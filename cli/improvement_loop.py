"""10步持续改进循环——自动化数据步骤（1-3, 8-10），供 cron 调用。

历史流程（来自 CLAUDE.md）:
1.抓行情 → 2.回写记录 → 3.比对预测 → 4.讨论需求 → 5.讨论代码
→ 6.制定计划 → 7.调代码 → 8.验证(backtest) → 9.检验(predict) → 10.执行(commit)

步骤 4-7 由 Claude 在 cron 提示词中处理。
此脚本执行步骤 1-3 + 8-9，输出摘要供 Claude 分析。
"""

import io
import json
import sys

# ---- Windows GBK 编码修复 ----
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from datetime import date, datetime, timedelta
from pathlib import Path


HISTORY_DIR = Path(".prediction_history")
RECORDS_FILE = HISTORY_DIR / "predictions_002594.json"


def step1_fetch(stock: str = "002594") -> dict:
    """步骤1: 抓行情（predict 命令输出）。"""
    import io as _io

    _saved = sys.stdout
    sys.stdout = _io.StringIO()
    try:
        from core.data_fetcher import fetch_normalized_data, fetch_realtime_quote, fetch_valuation_data
        from core.analyzers.technical import analyze as analyze_technical
        from core.analyzers.valuation import analyze as analyze_valuation
        from core.scoring import compute as compute_score
        from core.advice import generate as generate_advice
        from core.backtester import predict_direction
        from core.market_context import get_market_regime, market_boost, market_range_multiplier
        import statistics as _stats

        data = fetch_normalized_data(stock_code=stock, force_refresh=False)
        if not data.prices:
            return {"status": "error", "message": "数据获取失败"}

        prices = data.prices
        cur_price = prices[-1].close

        # 实时行情
        try:
            rt = fetch_realtime_quote(stock_code=stock)
            rt_price = rt.get("f43", 0) / 100
            if rt_price > 0:
                cur_price = rt_price
        except Exception:
            pass

        result = analyze_technical(data)
        try:
            valuation = fetch_valuation_data(stock_code=stock)
        except Exception:
            valuation = None
        result = analyze_valuation(result, valuation)
        score_result = compute_score(result)
        advice = generate_advice(score_result, result, current_price=cur_price)

        # 市场环境
        market = get_market_regime()
        advice.score = int(market_boost(advice.score, market))
        advice.score = min(100, max(0, advice.score))

        # 方向预测
        dir_pred = predict_direction(data.prices)

        # 价格预测
        closes = [p.close for p in prices[-20:]]
        momentum = 0.0
        if len(prices) >= 4:
            momentum = (
                (prices[-1].close - prices[-2].close) * 0.5 +
                (prices[-2].close - prices[-3].close) * 0.3 +
                (prices[-3].close - prices[-4].close) * 0.2
            )
        ma_bias = 0.0
        if result.ma_20 and result.ma_50:
            if cur_price > result.ma_20:
                ma_bias = -0.1
            elif cur_price < result.ma_50:
                ma_bias = +0.1
        rsi_bias = 0.0
        if result.rsi_14:
            if result.rsi_14 < 30:
                rsi_bias = +0.3
            elif result.rsi_14 > 70:
                rsi_bias = -0.3
        pred_close = cur_price + momentum * 0.3 + ma_bias + rsi_bias

        from core.prediction_tracker import record_prediction, get_calibration
        cal = get_calibration(stock)
        pred_close += cal.get("bias_correction", 0.0)
        atr_range = (result.atr_14 or 0) * 0.6 * market_range_multiplier(market)
        pred_low = pred_close - atr_range
        pred_high = pred_close + atr_range
        record_prediction(
            stock_code=stock,
            predicted_low=pred_low,
            predicted_high=pred_high,
            predicted_close=pred_close,
            current_price=cur_price,
        )

        return {
            "status": "ok",
            "stock": stock,
            "price": cur_price,
            "score": advice.score,
            "action": advice.action_label,
            "position_pct": advice.position_pct,
            "direction": dir_pred["direction"],
            "dir_confidence": dir_pred["confidence"],
            "pred_low": round(pred_low, 2),
            "pred_high": round(pred_high, 2),
            "pred_close": round(pred_close, 2),
            "pe_pct": result.pe_percentile,
            "pb_pct": result.pb_percentile,
            "rsi": result.rsi_14,
            "trend": result.trend,
            "rationale": advice.rationale,
            "buy_signals": score_result.buy_signals,
            "sell_signals": score_result.sell_signals,
        }
    finally:
        sys.stdout = _saved


def step2_backfill(stock: str, current_price: float) -> int:
    """步骤2: 回写记录——自动回填超过30分钟的旧预测。"""
    if not RECORDS_FILE.exists():
        return 0
    records = json.loads(RECORDS_FILE.read_text())
    now = datetime.now()
    backfilled = 0
    for r in records:
        if r.get("actual_close"):
            continue
        try:
            ts = datetime.fromisoformat(r["timestamp"])
        except (ValueError, KeyError):
            continue
        if now - ts > timedelta(minutes=30):
            r["actual_close"] = round(current_price, 2)
            r["error"] = round(current_price - float(r["predicted_close"]), 2)
            r["backfill_type"] = "auto"
            backfilled += 1
    if backfilled:
        RECORDS_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    return backfilled


def step3_compare() -> dict:
    """步骤3: 比对预测——统计准确率。"""
    from core.prediction_tracker import compute_accuracy
    return compute_accuracy("002594")


def step8_backtest(stock: str = "002594", days: int = 50) -> dict:
    """步骤8: 回测验证。"""
    from core.backtester import backtest_direction
    return backtest_direction(stock_code=stock, days=days)


def run() -> dict:
    """执行自动化步骤 2-9（步骤1由外部 predict 命令完成）。"""
    result = {
        "timestamp": datetime.now().isoformat(),
        "steps": {},
    }

    # 步骤1已由外部 python -m cli.main predict 完成
    # 这里做内部数据收集供步骤2-3使用
    predict_result = step1_fetch("002594")
    result["steps"]["1_fetch"] = predict_result

    if predict_result["status"] != "ok":
        result["status"] = "error"
        return result

    cur_price = predict_result["price"]

    # 步骤2: 回写记录
    n_backfilled = step2_backfill("002594", cur_price)
    result["steps"]["2_backfill"] = {"count": n_backfilled}

    # 步骤3: 比对预测
    accuracy = step3_compare()
    result["steps"]["3_compare"] = accuracy

    # 步骤8: 回测（每2小时跑一次，避免过频）
    now = datetime.now()
    should_backtest = now.hour % 2 == 0 and now.minute < 15
    if should_backtest:
        bt = step8_backtest("002594", days=50)
        result["steps"]["8_backtest"] = {
            "directional_accuracy": bt.get("directional_accuracy"),
            "recent_10": bt.get("recent_10_accuracy"),
            "up_acc": bt.get("up_accuracy"),
            "down_acc": bt.get("down_accuracy"),
        }
    else:
        result["steps"]["8_backtest"] = {"skipped": "非偶数整点，跳过回测"}

    # 步骤9: 检验（摘要已包含在步骤1中）
    result["steps"]["9_verify"] = {
        "score": predict_result["score"],
        "direction": predict_result["direction"],
        "action": predict_result["action"],
    }

    result["status"] = "ok"
    return result


def print_summary(result: dict) -> None:
    """打印步骤摘要，供 Claude 分析。"""
    if result["status"] != "ok":
        print("[ERROR] 10步循环失败")
        return

    s = result["steps"]
    f = s["1_fetch"]
    c = s["3_compare"]
    b = s["8_backtest"]

    print(f"[1抓行情] {f['stock']} 现价{f['price']} 评分{f['score']} {f['action']} 仓位{f['position_pct']}%")
    print(f"  方向:{f['direction']}({f['dir_confidence']}%置信) PE:{f['pe_pct']:.0f}%分位 PB:{f['pb_pct']:.0f}%分位 RSI:{f['rsi']:.0f}")
    if f["buy_signals"]:
        print(f"  买入信号: {' | '.join(f['buy_signals'])}")
    if f["sell_signals"]:
        print(f"  卖出信号: {' | '.join(f['sell_signals'])}")

    print(f"[2回写] 自动回填 {s['2_backfill']['count']} 条旧预测")

    if c.get("status") == "ok":
        print(f"[3比对] 预测{c['count']}次 | MAE:{c['mae']}元 | 方向准确率:{c['direction_accuracy']}% | 区间命中:{c['in_range_pct']}%")
    else:
        print(f"[3比对] 数据不足，继续积累")

    if "skipped" in b:
        print(f"[8回测] 跳过（{b['skipped']}）")
    else:
        print(f"[8回测] 方向:{b['directional_accuracy']}% | 近10次:{b['recent_10']}% | 涨:{b['up_acc']}% 跌:{b['down_acc']}%")

    print(f"[9检验] 评分:{f['score']} | 方向:{f['direction']} | 建议:{f['action']}")

    # 异常检测
    anomalies = []
    if f["score"] >= 80:
        anomalies.append(f"买入红色警报: 评分≥80——建议立即加仓！")
    if f["score"] <= 30:
        anomalies.append(f"强烈卖出警报: 评分≤30——建议清仓！")
    # 方向准确率: 短期方向~48%是天花板（市场有效假说），仅当>50样本且<20%才告警
    n_backfilled = c.get("count", 0)
    dir_acc = c.get("direction_accuracy", 50)
    if n_backfilled >= 50 and dir_acc < 20:
        anomalies.append(f"方向准确率异常低: {dir_acc}%（{n_backfilled}样本），可能模型退化")
    elif n_backfilled >= 30 and dir_acc < 10:
        anomalies.append(f"方向准确率严重退化: {dir_acc}%（{n_backfilled}样本）")
    if f["pe_pct"] is not None and f["pe_pct"] > 90:
        anomalies.append(f"PE分位>90%——极度高估")
    if f["pe_pct"] is not None and f["pe_pct"] < 10:
        anomalies.append(f"PE分位<10%——极度低估，历史级买入机会")

    if anomalies:
        print(f"\n[异常] 发现 {len(anomalies)} 个异常，需要 Claude 分析:")
        for a in anomalies:
            print(f"  {a}")
        print("  → 执行步骤4-7: 讨论需求→讨论代码→制定计划→调代码")
        print("  → 执行步骤10: git commit 保存改动")
    else:
        print(f"\n[正常] 无异常，跳过步骤4-7和步骤10")


if __name__ == "__main__":
    print(f"=== 10步持续改进循环 === {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()
    try:
        r = run()
        print_summary(r)
    except Exception as e:
        print(f"[CRASH] 循环异常: {e}")
        import traceback
        traceback.print_exc()
