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
    console.print(f"[bold]比亚迪 002594 实时分析[/bold]")
    console.print(f"时间: {now.strftime('%Y-%m-%d %H:%M')}")
    console.print()

    # ====== 数据 ======
    prices = fetch_price_history(stock_code=stock, days=500, force_refresh=True)
    if not prices:
        console.print("[red]价格数据获取失败[/red]")
        return
    latest = prices[-1]
    cur_price = latest.close

    # 实时行情
    try:
        rt = fetch_realtime_quote(stock_code=stock)
        rt_price = rt.get("f43", 0) / 100
        rt_pe = rt.get("f162", 0) / 100
        rt_mcap = rt.get("f116", 0) / 1e8
        if rt_price > 0:
            cur_price = rt_price
        console.print(
            f"[dim]实时: {rt.get('f57','')} {cur_price:.2f}  |  "
            f"PE {rt_pe:.1f}  |  市值 {rt_mcap:.0f}亿  |  "
            f"昨收 {rt.get('f60',0)/100:.2f}[/dim]"
        )
    except Exception:
        pass

    console.print()

    # ====== 完整分析流水线 ======
    _saved = sys.stdout
    sys.stdout = _io.StringIO()
    try:
        data = fetch_normalized_data(stock_code=stock, force_refresh=False)
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

    # ====== 价格预测 ======
    closes = [p.close for p in prices[-20:]]
    avg = _stats.mean(closes)
    stdev = _stats.stdev(closes)
    ups = sum(1 for p in prices[-10:] if p.close > p.open)
    ranges = [(p.high - p.low) / p.open * 100 for p in prices[-10:]]
    avg_range = _stats.mean(ranges)

    cal = get_calibration(stock)
    pred_close = cur_price + cal.get("bias_correction", 0.0)
    pred_range = stdev * 0.4 * cal.get("range_multiplier", 1.0)
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
    body += f"\n[dim]基于 {latest.date} 数据[/dim]"

    panel = Panel(body, title=header, border_style=color, padding=(1, 2))
    console.print(panel)

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

    # --- 关键指标摘要 ---
    console.print()
    summary = Table(title="关键指标")
    summary.add_column("估值", style="yellow")
    summary.add_column("技术", style="blue")
    summary.add_column("趋势", style="magenta")
    summary.add_column("近期", style="green")
    pe_str = f"PE分位 {result.pe_percentile:.0f}%" if result.pe_percentile else "PE N/A"
    pb_str = f"PB分位 {result.pb_percentile:.0f}%" if result.pb_percentile else "PB N/A"
    summary.add_row(
        f"{pe_str}\n{pb_str}",
        f"RSI {result.rsi_14:.0f}\nMACD {result.macd:.3f}" if result.rsi_14 else "N/A",
        f"{result.trend}\nMA20>{'MA50' if result.ma_20 and result.ma_50 and result.ma_20 > result.ma_50 else ''}",
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


@app.command()
def backfill(
    price: float = typer.Option(..., "--price", "-p", help="实际收盘价"),
    stock: str = typer.Option("002594", "--stock", "-s", help="股票代码"),
) -> None:
    """回填实际收盘价，计算预测误差。"""
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


if __name__ == "__main__":
    app()
