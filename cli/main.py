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
from datetime import date

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

        console.print("[yellow]使用模拟数据（离线模式）[/yellow]\n")
        data = generate_mock_data(stock_code=stock, start_price=price)
    else:
        from core.data_fetcher import fetch_normalized_data

        try:
            data = fetch_normalized_data(stock_code=stock, force_refresh=True)
        except Exception as e:
            console.print(f"[red]数据获取失败: {e}[/red]")
            console.print("[yellow]切换至模拟数据模式...[/yellow]\n")
            from core.data_fetcher import generate_mock_data

            data = generate_mock_data(stock_code=stock, start_price=price)

    if data.is_cached:
        console.print(f"[dim]数据来源: 缓存 ({data.cache_timestamp})[/dim]")

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
    if not mock:
        from core.analyzers.valuation import analyze as analyze_valuation
        from core.data_fetcher import fetch_valuation_data

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


if __name__ == "__main__":
    app()
