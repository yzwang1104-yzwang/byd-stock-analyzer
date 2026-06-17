"""11步持续改进循环——自动化数据步骤，供 cron 调用。

历史流程（来自 CLAUDE.md — 2026-06-16 最终版）:
1.预测(predict) → 2.抓行情(fetch) → 3.回写记录(backfill) → 4.比对预测值(compare)
→ 5.讨论需求 → 6.讨论代码 → 7.制定计划 → 8.改进代码
→ 9.验证(backtest) → 10.检验(predict) → 11.提交(commit)

步骤1:     python -m cli.main predict（用户可见完整输出）
步骤2-4:   脚本自动：抓行情+回写+比对
步骤9-10:  脚本自动：回测+检验
步骤5-8:   Claude 处理（仅当异常时触发）
步骤11:    Claude 处理（仅当步骤8修改了代码时触发）
"""

import io
import json
import sys

# ---- Windows GBK 编码修复 ----
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


HISTORY_DIR = Path(".prediction_history")


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
        except Exception as e:
            logger.warning(f"实时行情获取失败 for {stock}: {e}")

        result = analyze_technical(data)
        try:
            valuation = fetch_valuation_data(stock_code=stock)
        except Exception as e:
            logger.warning(f"估值数据获取失败 for {stock}: {e}")
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

        # 价格预测（共享模块）
        from core.predict import compute_price_prediction
        pred = compute_price_prediction(prices, result, stock, cur_price, market)
        pred_close = pred["pred_close"]
        pred_low = pred["pred_low"]
        pred_high = pred["pred_high"]
        momentum = pred["momentum"]
        ma_bias = pred["ma_bias"]
        rsi_bias = pred["rsi_bias"]

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
    records_file = HISTORY_DIR / f"predictions_{stock}.json"
    if not records_file.exists():
        return 0
    records = json.loads(records_file.read_text())
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
        records_file.write_text(json.dumps(records, ensure_ascii=False, indent=2))
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

    # 步骤9: 检验——独立验证预测质量
    verify_issues = []
    if predict_result["score"] >= 80 and predict_result["direction"] == "down":
        verify_issues.append("评分高但方向看跌，存在背离——需人工判断")
    if predict_result["score"] <= 30 and predict_result["direction"] == "up":
        verify_issues.append("评分低但方向看涨，信号矛盾——需人工判断")
    if accuracy.get("count", 0) >= 30 and accuracy.get("in_range_pct", 100) < 70:
        verify_issues.append(f"区间命中率仅{accuracy['in_range_pct']}%——模型可能需校准")
    result["steps"]["9_verify"] = {
        "score": predict_result["score"],
        "direction": predict_result["direction"],
        "action": predict_result["action"],
        "issues": verify_issues,
        "passed": len(verify_issues) == 0,
    }

    result["status"] = "ok"
    return result


def print_summary(result: dict) -> None:
    """打印11步摘要，供 Claude 分析。"""
    if result["status"] != "ok":
        print("[ERROR] 11步循环失败")
        return

    s = result["steps"]
    f = s["1_fetch"]
    c = s["3_compare"]
    b = s["8_backtest"]

    print(f"[1预测] python -m cli.main predict（见上方完整输出）")
    print(f"[2抓行情] {f['stock']} 现价{f['price']} 评分{f['score']} {f['action']} 仓位{f['position_pct']}%")
    print(f"  方向:{f['direction']}({f['dir_confidence']}%置信) PE:{f['pe_pct']:.0f}%分位 PB:{f['pb_pct']:.0f}%分位 RSI:{f['rsi']:.0f}")
    if f["buy_signals"]:
        print(f"  买入信号: {' | '.join(f['buy_signals'])}")
    if f["sell_signals"]:
        print(f"  卖出信号: {' | '.join(f['sell_signals'])}")

    print(f"[3回写] 自动回填 {s['2_backfill']['count']} 条旧预测")

    if c.get("status") == "ok":
        print(f"[4比对] 预测{c['count']}次 | MAE:{c['mae']}元 | 方向准确率:{c['direction_accuracy']}% | 区间命中:{c['in_range_pct']}%")
    else:
        print(f"[4比对] 数据不足，继续积累")

    if "skipped" in b:
        print(f"[9回测] 跳过（{b['skipped']}）")
    else:
        print(f"[9回测] 方向:{b['directional_accuracy']}% | 近10次:{b['recent_10']}% | 涨:{b['up_acc']}% 跌:{b['down_acc']}%")

    print(f"[10检验] 评分:{f['score']} | 方向:{f['direction']} | 建议:{f['action']}")

    # 异常检测
    anomalies = []
    if f["score"] >= 80:
        anomalies.append(f"买入红色警报: 评分>=80——建议立即加仓!")
    if f["score"] <= 30:
        anomalies.append(f"强烈卖出警报: 评分<=30——建议清仓!")
    n_backfilled = c.get("count", 0)
    dir_acc = c.get("direction_accuracy", 50)
    dir_samples = c.get("direction_total", 0)
    # 仅当方向样本>=30且准确率<20%才告警（小样本不告警）
    # 方向准确率天花板~48%（市场有效假说），低样本不具统计意义
    if dir_samples >= 30 and dir_acc < 20:
        anomalies.append(f"方向准确率异常低: {dir_acc}%（{dir_samples}样本），可能模型退化")
    if f["pe_pct"] is not None and f["pe_pct"] > 90:
        anomalies.append(f"PE分位>90%——极度高估")
    if f["pe_pct"] is not None and f["pe_pct"] < 10:
        anomalies.append(f"PE分位<10%——极度低估，历史级买入机会")

    if anomalies:
        print(f"\n[异常] 发现 {len(anomalies)} 个异常，触发 Claude 介入:")
        for a in anomalies:
            print(f"  {a}")
        print("  -> [5]讨论需求 → [6]讨论代码 → [7]制定计划 → [8]改进代码")
        print("  -> [11] git commit 保存改动")
    else:
        print(f"\n[正常] 无异常，跳过步骤5-8和步骤11")


if __name__ == "__main__":
    print(f"=== 11步持续改进循环 === {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()
    try:
        r = run()
        print_summary(r)
    except Exception as e:
        print(f"[CRASH] 循环异常: {e}")
        import traceback
        traceback.print_exc()
