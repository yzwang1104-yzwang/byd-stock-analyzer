"""CLI 入口——比亚迪股票买入时机分析工具。

usage:
    python cli/main.py --price 89.0            # 快速分析
    python cli/main.py --price 89.0 --verbose  # 详细分析
    python cli/main.py --price 89.0 --mock     # 使用模拟数据（离线模式）
"""

import io
import logging
import os
import sys
import warnings
from datetime import date, datetime

# ---- 抑制调试输出 ----
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# 重定向 stdout 为 UTF-8（处理 Windows GBK）
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="byd-analyzer",
    help="比亚迪(BYD 002594)股票买入时机智能分析工具",
)
console = Console()

def _valuation_label(pct: float | None) -> str:
    """PE/PB 分位 → 解释标签。≤30%=便宜, 30-70%=合理, >70%=偏贵"""
    if pct is None:
        return "N/A"
    if pct <= 30:
        return "偏低(便宜)"
    elif pct <= 70:
        return "合理(中性)"
    else:
        return "偏高(贵)"


DISCLAIMER = (
    "[dim]分析结果仅供参考，不构成任何投资建议。"
    "投资有风险，入市需谨慎。[/dim]"
)


def _validate_price(value: float) -> float:
    """校验价格为正数。"""
    if value <= 0:
        raise typer.BadParameter(f"股价必须为正数，收到: {value}")
    return value


@app.command()
def analyze(
    price: float = typer.Option(..., "--price", "-p", help="比亚迪当前股价（元）", callback=_validate_price),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示详细指标"),
    mock: bool = typer.Option(False, "--mock", help="使用模拟数据（离线模式）"),
    stock: str = typer.Option("002594", "--stock", "-s", help="股票代码"),
) -> None:
    """分析比亚迪当前股价的买入时机。

    输出: 综合评分 + 操作建议 + 建议仓位 + 关键依据。
    """
    # ---- Phase 2: 数据获取 ----
    if mock:
        from core.data_fetcher import generate_mock_data

        console.print("[yellow]使用模拟数据（离线模式）[/yellow]")
        data = generate_mock_data(stock_code=stock, start_price=price)
        realtime = None
    else:
        from core.data_fetcher import fetch_normalized_data, fetch_realtime_quote

        try:
            data = fetch_normalized_data(stock_code=stock, force_refresh=True)
            if data.is_cached:
                console.print(f"[dim]价格数据: 缓存[/dim]")
            else:
                console.print(f"[dim]价格数据: 腾讯 K线 + 东方财富实时[/dim]")
        except Exception as e:
            console.print(f"[red]价格数据获取失败: {e}[/red]")
            console.print("[yellow]切换至模拟数据...[/yellow]")
            from core.data_fetcher import generate_mock_data
            data = generate_mock_data(stock_code=stock, start_price=price)

        # 实时行情
        try:
            realtime = fetch_realtime_quote(stock_code=stock)
            console.print(
                f"[dim]实时行情: {realtime.get('f57','')}  "
                f"现价 {realtime.get('f43',0)/100:.2f}  |  "
                f"昨收 {realtime.get('f60',0)/100:.2f}  |  "
                f"PE(静态) {realtime.get('f162',0)/100:.1f}  |  "
                f"总市值 {realtime.get('f116',0)/1e8:.0f}亿[/dim]"
            )
        except Exception:
            realtime = None

    # ---- Phase 3: 技术分析 ----
    from core.analyzers.technical import analyze as analyze_technical

    # 抑制 pandas-ta 内部 DataFrame 打印
    _original_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        result = analyze_technical(data)
    finally:
        sys.stdout = _original_stdout

    # ---- Phase 4: 估值分析 ----
    from core.analyzers.valuation import analyze as analyze_valuation
    from core.data_fetcher import fetch_valuation_data

    if not mock:
        try:
            valuation = fetch_valuation_data(stock_code=stock)
        except Exception:
            valuation = None
        result = analyze_valuation(result, valuation)
    else:
        # Mock 估值数据
        result.pe_percentile = 25.0
        result.pb_percentile = 30.0
        result.vs_industry_pe = "低于"

    # ---- Phase 5: 评分 ----
    from core.scoring import compute as compute_score

    score_result = compute_score(result)

    # ---- Phase 6: 决策 ----
    from core.advice import generate as generate_advice

    advice = generate_advice(score_result, result, stock_name="比亚迪", current_price=price)

    # ---- Phase 7: 输出 ----
    _render_output(advice, score_result, result, price, verbose)


def _render_output(advice, score_result, analysis, price, verbose):
    """渲染 CLI 输出（OUT-01 ~ OUT-05, COMP-01 ~ COMP-03）。"""

    # 主输出面板
    action_colors = {
        "strong_buy": "bold green",
        "buy": "green",
        "hold": "yellow",
        "sell": "red",
        "strong_sell": "bold red",
    }
    action_emoji = {
        "strong_buy": "[BUY++]",
        "buy": "[BUY]",
        "hold": "[WAIT]",
        "sell": "[SELL]",
        "strong_sell": "[SELL--]",
    }

    color = action_colors.get(advice.action, "white")
    emoji = action_emoji.get(advice.action, "[?]")

    # 一行结论（OUT-01）
    header = (
        f"[{color}]{emoji} {advice.action_label}[/{color}]  |  "
        f"评分: [{color}]{advice.score}/100[/{color}]  |  "
        f"仓位: [{color}]{advice.position_pct}%[/{color}]  |  "
        f"置信度: {advice.confidence}"
    )

    # 依据
    body = f"\n{advice.rationale}\n"

    # 时效提示（OUT-05）
    body += f"\n[dim]基于 {date.today()} 收盘数据，建议在 24 小时内决策[/dim]"

    panel = Panel(
        body,
        title=header,
        border_style=color,
        padding=(1, 2),
    )
    console.print(panel)

    # 详细指标（OUT-03, --verbose）
    if verbose and advice.details:
        console.print()
        console.print("[bold]详细分析[/bold]")
        console.print("─" * 60)
        for line in advice.details:
            if line.startswith("==="):
                console.print(f"\n[bold cyan]{line}[/bold cyan]")
            elif line and not line.startswith(" "):
                console.print(f"  {line}")
        console.print("─" * 60)

    # 评分细项表格
    if verbose:
        bd = score_result.breakdown
        table = Table(title="评分细项")
        table.add_column("因子", style="cyan")
        table.add_column("加权得分", justify="right")
        table.add_column("原始分", justify="right")
        table.add_column("权重", justify="right")

        for name, score_val, weight in [
            ("估值", bd.valuation_score, "35%"),
            ("技术", bd.technical_score, "30%"),
            ("趋势", bd.trend_score, "20%"),
            ("量能", bd.volume_score, "10%"),
            ("情绪", bd.sentiment_score, "5%"),
        ]:
            raw = score_val / (float(weight.strip("%")) / 100) if weight != "0%" else 0
            table.add_row(name, f"{score_val:.1f}", f"{raw:.0f}", weight)

        table.add_row("[bold]总计[/bold]", f"[bold]{bd.total:.1f}[/bold]", "", "[bold]100%[/bold]")
        console.print(table)

    # 合规免责（COMP-01/02/03）
    console.print()
    console.print(DISCLAIMER)
    console.print()


@app.command()
def predict(
    stock: str = typer.Option("002594", "--stock", "-s", help="股票代码"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示详细指标"),
) -> None:
    """比亚迪上午收盘预测 + 买入建议（合二为一）。"""
    import io as _io, statistics as _stats

    from core.data_fetcher import (
        fetch_normalized_data,
        fetch_price_history,
        fetch_realtime_quote,
        fetch_valuation_data,
    )
    from core.prediction_tracker import get_calibration, record_prediction

    now = datetime.now()
    console.print()
    stock_label = f"{stock} 实时分析" if stock != "002594" else "比亚迪 002594 实时分析"
    console.print(f"[bold]{stock_label}[/bold]")
    console.print(f"时间: {now.strftime('%Y-%m-%d %H:%M')}")
    console.print()

    # ====== 统一数据获取（分析 + 预测共用） ======
    _saved = sys.stdout
    sys.stdout = _io.StringIO()
    data = fetch_normalized_data(stock_code=stock, force_refresh=False)
    sys.stdout = _saved

    if not data.prices:
        console.print("[red]价格数据获取失败[/red]")
        return

    prices = data.prices
    cur_price = prices[-1].close

    # 实时行情
    try:
        rt = fetch_realtime_quote(stock_code=stock)
        rt_price = rt.get("f43", 0) / 100
        if rt_price > 0:
            cur_price = rt_price
        console.print(
            f"[dim]实时: {rt.get('f57','')} {cur_price:.2f}  |  "
            f"PE {rt.get('f162',0)/100:.1f}  |  市值 {rt.get('f116',0)/1e8:.0f}亿  |  "
            f"昨收 {rt.get('f60',0)/100:.2f}[/dim]"
        )
    except Exception:
        console.print(f"[dim]价格: {cur_price:.2f} (K线)[/dim]")

    console.print()

    # ====== 完整分析流水线 ======
    sys.stdout = _io.StringIO()
    try:
        from core.analyzers.technical import analyze as analyze_technical
        result = analyze_technical(data)
        try:
            valuation = fetch_valuation_data(stock_code=stock)
        except Exception:
            valuation = None
        from core.analyzers.valuation import analyze as analyze_valuation
        result = analyze_valuation(result, valuation)
        from core.scoring import compute as compute_score
        score_result = compute_score(result)
        from core.advice import generate as generate_advice
        advice = generate_advice(score_result, result, current_price=cur_price)
    finally:
        sys.stdout = _saved

    # ====== 大盘环境（新增维度） ======
    from core.market_context import (
        get_market_regime,
        market_boost,
        market_range_multiplier,
    )
    market = get_market_regime()
    advice.score = int(market_boost(advice.score, market))
    advice.score = min(100, max(0, advice.score))
    mkt_mult = market_range_multiplier(market)

    # ====== 价格预测（融合技术指标） ======
    closes = [p.close for p in prices[-20:]]
    avg = _stats.mean(closes)
    stdev = _stats.stdev(closes)
    ups = sum(1 for p in prices[-10:] if p.close > p.open)
    ranges = [(p.high - p.low) / p.open * 100 for p in prices[-10:]]
    avg_range = _stats.mean(ranges)

    # 近期动量（3日涨跌幅加权）
    momentum = 0.0
    if len(prices) >= 4:
        momentum = (
            (prices[-1].close - prices[-2].close) * 0.5 +
            (prices[-2].close - prices[-3].close) * 0.3 +
            (prices[-3].close - prices[-4].close) * 0.2
        )

    # ATR 波动率预测区间
    atr_range = result.atr_14 * 0.6 if result.atr_14 else stdev * 0.4

    # MA 位置修正
    ma_bias = 0.0
    if result.ma_20 and result.ma_50:
        if cur_price > result.ma_20:
            ma_bias = -0.1  # 高于MA20，均值回归向下
        elif cur_price < result.ma_50:
            ma_bias = +0.1  # 低于MA50，均值回归向上

    # RSI 极端修正
    rsi_bias = 0.0
    if result.rsi_14:
        if result.rsi_14 < 30:
            rsi_bias = +0.3  # 超卖，反弹概率大
        elif result.rsi_14 > 70:
            rsi_bias = -0.3  # 超买，回调概率大

    cal = get_calibration(stock)
    pred_close = cur_price + momentum * 0.3 + ma_bias + rsi_bias + cal.get("bias_correction", 0.0)
    pred_range = atr_range * cal.get("range_multiplier", 1.0) * mkt_mult
    pred_low = pred_close - pred_range
    pred_high = pred_close + pred_range

    rid = record_prediction(
        stock_code=stock,
        predicted_low=pred_low,
        predicted_high=pred_high,
        predicted_close=pred_close,
        current_price=cur_price,
    )

    # ====== 输出 ======
    action_colors = {
        "strong_buy": "bold green", "buy": "green", "hold": "yellow",
        "sell": "red", "strong_sell": "bold red",
    }
    action_emoji = {
        "strong_buy": "[STRONG BUY]", "buy": "[BUY]", "hold": "[WAIT]",
        "sell": "[SELL]", "strong_sell": "[STRONG SELL]",
    }
    color = action_colors.get(advice.action, "white")
    emoji = action_emoji.get(advice.action, "[?]")

    # --- 主面板 ---
    header = (
        f"[{color}]{emoji} {advice.action_label}[/{color}]  |  "
        f"评分: [{color}]{advice.score}/100[/{color}]  |  "
        f"仓位: [{color}]{advice.position_pct}%[/{color}]  |  "
        f"置信度: {advice.confidence}"
    )

    body = f"\n{advice.rationale}\n"
    body += f"\n[dim]基于 {prices[-1].date} 数据[/dim]"

    panel = Panel(body, title=header, border_style=color, padding=(1, 2))
    console.print(panel)

    # --- 买入警报（评分 ≥ 80） ---
    if advice.score >= 80:
        alert_text = (
            f"[bold white on red]  ⚡ 买入时机成熟！评分 {advice.score}/100 — 建议立即加仓 ⚡  [/bold white on red]\n"
            f"[bold red]  建议仓位: {advice.position_pct}%  |  {advice.action_label}  |  {advice.rationale}[/bold red]"
        )
        alert_panel = Panel(alert_text, border_style="bold red", padding=(1, 1))
        console.print(alert_panel)

    # --- 预测面板 ---
    cal_info = ""
    if cal["ready"]:
        cal_info = (
            f"  校准状态: 偏差 {cal['bias_correction']:+.2f}  |  "
            f"方向准确率 {cal['direction_accuracy']:.0f}%  |  "
            f"基于 {cal['based_on']} 次历史"
        )

    pred_table = Table(title="上午收盘预测", border_style="cyan")
    pred_table.add_column("预测区间", style="cyan", justify="center")
    pred_table.add_column("最可能", style="bold cyan", justify="center")
    pred_table.add_column("基准", justify="center")
    pred_table.add_column("记录ID", justify="center")
    pred_table.add_row(
        f"{pred_low:.2f} — {pred_high:.2f} 元",
        f"{pred_close:.2f} 元",
        f"{cur_price:.2f} 元",
        f"#{rid}",
    )
    console.print(pred_table)
    if cal_info:
        console.print(f"[dim]{cal_info}[/dim]")

    # 预测因子明细
    factors = []
    if abs(momentum) > 0.01:
        factors.append(f"动量 {momentum:+.2f}")
    if abs(ma_bias) > 0.01:
        factors.append(f"MA回归 {ma_bias:+.2f}")
    if abs(rsi_bias) > 0.01:
        factors.append(f"RSI修正 {rsi_bias:+.2f}")
    if factors:
        console.print(f"[dim]预测因子: {' | '.join(factors)} | 区间基于 ATR({result.atr_14:.2f})[/dim]")
    # 市场环境
    if market.get("note") == "OK":
        regime_labels = {"bull": "牛市 ↑", "bear": "熊市 ↓", "sideways": "震荡 →"}
        regime_style = {"bull": "green", "bear": "red", "sideways": "yellow"}
        rl = regime_labels.get(market["regime"], "?")
        rs = regime_style.get(market["regime"], "white")
        boost_str = f"评分{market_boost(0, market):+.0f}" if market_boost(0, market) != 0 else "评分不变"
        console.print(
            f"[dim]大盘环境: [{rs}]{rl}[/{rs}] | "
            f"上证50 {market['index_level']:.2f} | "
            f"近5日 {market['momentum_5d_pct']:+.1f}% | "
            f"RSI {market['market_rsi']} | "
            f"{boost_str} | 区间×{mkt_mult}[/dim]"
        )

    # --- 方向预测 + 二维决策 ---
    from core.backtester import predict_direction

    dir_pred = predict_direction(data.prices)
    direction = dir_pred["direction"]
    dir_conf = dir_pred["confidence"]
    up_votes = sum(1 for s in dir_pred["signals"] if "↑" in s)
    down_votes = sum(1 for s in dir_pred["signals"] if "↓" in s)
    signals_short = " | ".join(dir_pred["signals"][:3]) if dir_pred["signals"] else "无信号"

    # 二维决策矩阵
    score = advice.score
    if score >= 70 and direction == "up":
        matrix = ("强烈买入", "bold green")
    elif score >= 70 and direction == "down":
        matrix = ("等待低吸", "green")
    elif score >= 50 and direction == "up":
        matrix = ("轻仓试探", "green")
    elif score >= 50 and direction == "down":
        matrix = ("建议卖出", "red")
    elif score < 50 and direction == "up":
        matrix = ("观望等待", "yellow")
    elif score < 50 and direction == "down":
        matrix = ("强烈卖出", "bold red")
    else:
        matrix = ("信号不足", "yellow")

    dir_labels = {"up": "↑ 看涨", "down": "↓ 看跌", "flat": "→ 平盘"}
    dir_color_styles = {"up": "green", "down": "red", "flat": "yellow"}

    dir_style = dir_color_styles.get(direction, "white")
    console.print(
        f"[dim]方向预测: [{dir_style}]{dir_labels.get(direction, '?')}[/{dir_style}] "
        f"({dir_conf}%置信) | {up_votes}↑{down_votes}↓ | "
        f"决策: [bold {matrix[1]}]{matrix[0]}[/bold {matrix[1]}] "
        f"({score}分 × {direction})[/dim]"
    )
    if signals_short and signals_short != "无信号":
        console.print(f"[dim]  信号: {signals_short}[/dim]")

    # --- 关键指标摘要 ---
    console.print()
    summary = Table(title="关键指标")
    summary.add_column("估值", style="yellow")
    summary.add_column("技术", style="blue")
    summary.add_column("趋势", style="magenta")
    summary.add_column("近期", style="green")
    pe_str = f"市盈率(PE)分位 {result.pe_percentile:.0f}% {_valuation_label(result.pe_percentile)}" if result.pe_percentile else "市盈率(PE) N/A"
    pb_str = f"市净率(PB)分位 {result.pb_percentile:.0f}% {_valuation_label(result.pb_percentile)}" if result.pb_percentile else "市净率(PB) N/A"
    summary.add_row(
        f"{pe_str}\n{pb_str}",
        f"RSI {result.rsi_14:.0f}\nMACD {result.macd:.3f}" if result.rsi_14 else "N/A",
        f"{result.trend}\nMA20{' > MA50' if result.ma_20 and result.ma_50 and result.ma_20 > result.ma_50 else ' < MA50' if result.ma_20 and result.ma_50 else ''}",
        f"{ups}阳{10-ups}阴\n振幅{avg_range:.1f}%",
    )
    console.print(summary)

    # --- 详细 ---
    if verbose and advice.details:
        console.print()
        console.print("[bold]详细分析[/bold]")
        console.print("─" * 60)
        for line in advice.details:
            if line.startswith("==="):
                console.print(f"\n[bold cyan]{line}[/bold cyan]")
            elif line:
                console.print(f"  {line}")
        console.print("─" * 60)

        bd = score_result.breakdown
        table = Table(title="评分细项")
        table.add_column("因子", style="cyan")
        table.add_column("加权得分", justify="right")
        table.add_column("原始分", justify="right")
        table.add_column("权重", justify="right")
        for name, sv, w in [
            ("估值", bd.valuation_score, "35%"), ("技术", bd.technical_score, "30%"),
            ("趋势", bd.trend_score, "20%"), ("量能", bd.volume_score, "10%"),
            ("情绪", bd.sentiment_score, "5%"),
        ]:
            raw = sv / (float(w.strip("%")) / 100)
            table.add_row(name, f"{sv:.1f}", f"{raw:.0f}", w)
        table.add_row("[bold]总计[/bold]", f"[bold]{bd.total:.1f}[/bold]", "", "[bold]100%[/bold]")
        console.print(table)

    console.print()
    console.print(DISCLAIMER)
    console.print()

    # --- 自动回填 ---
    _auto_backfill(stock, cur_price)


def _auto_backfill(stock: str, current_price: float) -> None:
    """用当前价自动回填超过30分钟的旧预测。"""
    import json as _json
    from datetime import datetime as _dt, timedelta as _td
    from pathlib import Path as _Path

    records_file = _Path(".prediction_history") / f"predictions_{stock}.json"
    if not records_file.exists():
        return
    records = _json.loads(records_file.read_text())
    now = _dt.now()
    backfilled = 0
    for r in records:
        if r["actual_close"]:
            continue
        try:
            ts = _dt.fromisoformat(r["timestamp"])
        except ValueError:
            continue
        if now - ts > _td(minutes=30):
            r["actual_close"] = round(current_price, 2)
            r["error"] = round(current_price - float(r["predicted_close"]), 2)
            backfilled += 1
    if backfilled:
        records_file.write_text(_json.dumps(records, ensure_ascii=False, indent=2))
        console.print(f"[dim]自动回填: {backfilled} 条旧预测 → 实际价 {current_price:.2f}[/dim]")


@app.command()
def backfill(
    price: float = typer.Option(..., "--price", "-p", help="实际收盘价"),
    stock: str = typer.Option("002594", "--stock", "-s", help="股票代码"),
) -> None:
    """回填实际收盘价，计算预测误差。"""
    if price <= 0:
        console.print(f"[red]错误: 价格必须为正数，收到 {price}[/red]")
        return
    from core.prediction_tracker import backfill_actual, compute_accuracy

    n = backfill_actual(stock_code=stock, actual_price=price)
    console.print(f"[green]已回填 {n} 条预测记录，实际价 {price:.2f}[/green]")

    stats = compute_accuracy(stock)
    if stats["status"] == "ok":
        console.print()
        console.print(f"[bold]预测准确率报告[/bold] ({stats['count']} 次已完成)")
        console.print(f"  平均绝对误差: {stats['mae']} 元")
        console.print(f"  均方根误差:   {stats['rmse']} 元")
        console.print(f"  平均偏差:     {stats['mean_bias']:+.2f} 元 (正=预测偏低)")
        console.print(f"  方向准确率:   {stats['direction_accuracy']:.0f}%")
        console.print(f"  区间命中率:   {stats['in_range_pct']:.0f}%")


@app.command()
def backtest(
    days: int = typer.Option(200, "--days", "-d", help="回测天数"),
    stock: str = typer.Option("002594", "--stock", "-s", help="股票代码"),
) -> None:
    """6指标投票法回测——验证方向预测准确率。"""
    from core.backtester import backtest_direction

    console.print(f"[bold]方向预测回测 (6指标投票法)[/bold]")
    console.print(f"股票: {stock} | 回测天数: {days}")
    console.print()

    with console.status("[bold green]回测中..."):
        result = backtest_direction(stock_code=stock, days=days)

    if result["status"] != "ok":
        console.print(f"[red]回测失败: {result.get('status')}, 数据量: {result.get('count', 0)}[/red]")
        return

    # 总览
    console.print(f"[bold]纯方向准确率: {result['directional_accuracy']}%[/bold] "
                  f"({result['directional_total']} 次有信号)")
    console.print(f"  含\"平\"总准确率: {result['overall_accuracy']}% ({result['total']} 次)")
    console.print(f"  无信号(平)比例: {result['flat_rate']}% ({result['flat_count']}/{result['total']})")
    console.print(f"  预测涨准确率: {result['up_accuracy']}%")
    console.print(f"  预测跌准确率: {result['down_accuracy']}%")
    console.print(f"  近10次准确率: {result['recent_10_accuracy']}%")
    console.print()

    # 按置信度
    conf_table = Table(title="按置信度分组")
    conf_table.add_column("置信度", justify="center")
    conf_table.add_column("次数", justify="right")
    conf_table.add_column("准确率", justify="right")
    h = result
    conf_table.add_row("高(≥70%)", str(h["high_conf_count"]), f"{h['high_conf_accuracy']}%")
    conf_table.add_row("中(50-69%)", str(h["med_conf_count"]), f"{h['med_conf_accuracy']}%")
    conf_table.add_row("低(<50%)", str(h["low_conf_count"]), f"{h['low_conf_accuracy']}%")
    console.print(conf_table)

    # 最近5条样本
    console.print()
    console.print("[bold]最近5条预测样本[/bold]")
    for r in result["sample_results"]:
        mark = "[green]✓[/green]" if r["correct"] else "[red]✗[/red]"
        conf_str = f"({r['confidence']}%)"
        console.print(
            f"  {mark} {r['date']} {r['close']:.2f} | "
            f"预测: {r['predicted']} {conf_str} | 实际: {r['actual']}"
        )
        console.print(f"    [dim]信号: {' | '.join(r['signals'][:3])}[/dim]")

    console.print()
    console.print(DISCLAIMER)


@app.command()
def scan(
    stocks: str = typer.Option("002594,920839,600370,600567", "--stocks", help="股票代码列表，逗号分隔"),
) -> None:
    """多股票快速扫描——对比评分和方向。"""
    import io as _io

    codes = [s.strip() for s in stocks.split(",")]
    results = []

    for code in codes:
        _saved = sys.stdout
        sys.stdout = _io.StringIO()
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
            from core.backtester import predict_direction
            dp = predict_direction(data.prices)
            status = "OK"
        except Exception as e:
            status = str(e)[:40]
            advice = None
            dp = None
        finally:
            sys.stdout = _saved

        if status == "OK" and advice:
            results.append({
                "code": code,
                "price": data.latest_price,
                "score": advice.score,
                "action": advice.action_label,
                "direction": dp["direction"] if dp else "?",
                "pe_pct": result.pe_percentile,
                "pb_pct": result.pb_percentile,
                "trend": result.trend,
                "rsi": result.rsi_14,
            })
        else:
            results.append({"code": code, "price": 0, "score": 0, "action": "数据失败", "direction": "?", "pe_pct": None, "pb_pct": None, "trend": "?", "rsi": None, "error": status})

    # 输出
    table = Table(title="多股票扫描")
    table.add_column("代码", style="cyan")
    table.add_column("现价", justify="right")
    table.add_column("评分", justify="right")
    table.add_column("建议", justify="center")
    table.add_column("方向", justify="center")
    table.add_column("市盈率(PE)分位", justify="right")
    table.add_column("市净率(PB)分位", justify="right")
    table.add_column("趋势", justify="center")

    for r in results:
        score_color = "green" if r["score"] >= 70 else ("red" if r["score"] < 50 else "yellow")
        dir_label = {"up": "↑", "down": "↓", "flat": "→"}.get(r["direction"], "?")
        pe_str = f'{r["pe_pct"]:.0f}% {_valuation_label(r["pe_pct"])}' if r["pe_pct"] else "N/A"
        pb_str = f'{r["pb_pct"]:.0f}% {_valuation_label(r["pb_pct"])}' if r["pb_pct"] else "N/A"
        table.add_row(
            r["code"],
            f'{r["price"]:.2f}',
            f'[{score_color}]{r["score"]}[/{score_color}]',
            r["action"],
            dir_label,
            pe_str,
            pb_str,
            r["trend"],
        )
    console.print(table)
    console.print()
    console.print(DISCLAIMER)


if __name__ == "__main__":
    # 支持两种调用方式:
    #   python -m cli.main analyze --price 91.0  (typer 子命令)
    #   python -m cli.main --price 91.0           (直接参数, 等同于 analyze)
    import sys as _sys

    if len(_sys.argv) > 1 and _sys.argv[1] in ("analyze", "predict", "backfill", "backtest", "scan"):
        app()
    else:
        # 默认走 analyze 命令
        app(["analyze"] + _sys.argv[1:])
