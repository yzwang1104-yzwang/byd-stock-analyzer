"""多股票扫描排名 — 从全股票池中筛选最佳买入标的。"""
import os, sys, io, json
import numpy as np
import pandas as pd
from datetime import date

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

STOCK_NAMES = {
    "000001": "平安银行", "000002": "万科A", "000063": "中兴通讯",
    "000333": "美的集团", "000568": "泸州老窖", "000625": "长安汽车",
    "000651": "格力电器", "000725": "京东方A", "000858": "五粮液",
    "001979": "招商蛇口", "002050": "三花智控", "002230": "科大讯飞",
    "002352": "顺丰控股", "002371": "北方华创", "002415": "海康威视",
    "002460": "赣锋锂业", "002466": "天齐锂业", "002475": "立讯精密",
    "002594": "比亚迪", "002625": "光启技术", "002714": "牧原股份",
    "002920": "德赛西威", "300059": "东方财富", "300124": "汇川技术",
    "300274": "阳光电源", "300750": "宁德时代", "300760": "迈瑞医疗",
    "600028": "中国石化", "600029": "南方航空", "600030": "中信证券",
    "600036": "招商银行", "600104": "上汽集团", "600111": "北方稀土",
    "600276": "恒瑞医药", "600309": "万华化学", "600370": "*ST三房",
    "600426": "华鲁恒升", "600436": "片仔癀", "600438": "通威股份",
    "600519": "贵州茅台", "600567": "山鹰国际", "600585": "海螺水泥",
    "600690": "海尔智家", "600699": "均胜电子", "600760": "中航沈飞",
    "600809": "山西汾酒", "600887": "伊利股份", "600893": "航发动力",
    "600900": "长江电力", "600941": "中国移动",
    "601012": "隆基绿能", "601111": "中国国航", "601127": "赛力斯",
    "601166": "兴业银行", "601318": "中国平安", "601398": "工商银行",
    "601628": "中国人寿", "601668": "中国建筑", "601689": "拓普集团",
    "601728": "中国电信", "601857": "中国石油", "601888": "中国中免",
    "601899": "紫金矿业", "601919": "中远海控", "601939": "建设银行",
    "601985": "中国核电", "603259": "药明康德", "603288": "海天味业",
    "603501": "韦尔股份", "603799": "华友钴业", "603993": "洛阳钼业",
    "688012": "中微公司", "688041": "海光信息", "688256": "寒武纪",
    "688981": "中芯国际", "920839": "北证50",
}


def analyze_stock(code):
    """快速分析单只股票，返回评分+信号。"""
    price_path = f".cache/prices_{code}.csv"
    val_path = f".cache/valuation_{code}.csv"

    if not os.path.exists(price_path):
        return None

    try:
        df = pd.read_csv(price_path, index_col=0, parse_dates=True)
        if len(df) < 50:
            return None
    except Exception:
        return None

    close = df["close"]
    latest_price = close.iloc[-1]

    # --- 技术指标 ---
    ma20 = close.rolling(20).mean().iloc[-1]
    ma50 = close.rolling(50).mean().iloc[-1]

    # RSI14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_now = rsi.iloc[-1]

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    dif_now = dif.iloc[-1]
    dea_now = dea.iloc[-1]
    macd_gap = dif_now - dea_now

    # Bollinger position
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_low = bb_mid - 2 * bb_std
    bb_pos = (close - bb_low) / (4 * bb_std)

    # 20-day change
    chg_20d = (close.iloc[-1] - close.iloc[-20]) / close.iloc[-20] * 100 if len(close) >= 20 else 0

    # --- 估值 ---
    pe_pct = None
    pb_pct = None
    if os.path.exists(val_path):
        try:
            vdf = pd.read_csv(val_path)
            if "current_pe" in vdf.columns:
                pe_raw = str(vdf["pe_history"].iloc[0]) if "pe_history" in vdf.columns else ""
                if pe_raw:
                    pe_vals = [float(x) for x in pe_raw.split("|") if x]
                    if pe_vals and len(pe_vals) > 10:
                        pe_now = vdf["current_pe"].iloc[0]
                        pe_pct = (sum(1 for v in pe_vals if v < pe_now) / len(pe_vals)) * 100
            if "current_pb" in vdf.columns:
                pb_raw = str(vdf["pb_history"].iloc[0]) if "pb_history" in vdf.columns else ""
                if pb_raw:
                    pb_vals = [float(x) for x in pb_raw.split("|") if x]
                    if pb_vals and len(pb_vals) > 10:
                        pb_now = vdf["current_pb"].iloc[0]
                        pb_pct = (sum(1 for v in pb_vals if v < pb_now) / len(pb_vals)) * 100
        except Exception:
            pass

    # --- 趋势 ---
    if ma20 > ma50:
        trend = "up"
    elif abs(ma20 - ma50) / ma50 < 0.02:
        trend = "sideways"
    else:
        trend = "down"

    # --- 评分 ---
    score = 50.0

    # PE分位 (35%权重)
    if pe_pct is not None:
        if pe_pct < 10: score += 18
        elif pe_pct < 30: score += 10
        elif pe_pct < 50: score += 3
        elif pe_pct > 85: score -= 12
    else:
        score += 3

    if pb_pct is not None:
        if pb_pct < 10: score += 8
        elif pb_pct > 90: score -= 8

    if not np.isnan(rsi_now):
        if rsi_now < 20: score += 15
        elif rsi_now < 30: score += 8
        elif rsi_now < 40: score += 2
        elif rsi_now > 80: score -= 12
        elif rsi_now > 70: score -= 5

    if trend == "up": score += 10
    elif trend == "down": score -= 8

    if macd_gap > 0: score += 6
    elif macd_gap > -0.03: score += 3

    bb_now = bb_pos.iloc[-1]
    if not np.isnan(bb_now):
        if bb_now < 0.1: score += 8
        elif bb_now < 0.25: score += 4
        elif bb_now > 0.85: score -= 8

    score = max(0, min(100, score))

    # --- 信号 ---
    signals = []
    if not np.isnan(rsi_now) and rsi_now < 30: signals.append(f"RSI{rsi_now:.0f}超卖")
    if pe_pct is not None and pe_pct < 15: signals.append(f"PE{pe_pct:.0f}%极低")
    if pb_pct is not None and pb_pct < 15: signals.append(f"PB{pb_pct:.0f}%极低")
    if macd_gap > 0: signals.append("MACD金叉")
    elif macd_gap > -0.03: signals.append("MACD近金叉")
    if trend == "up": signals.append("趋势向上")
    if chg_20d < -15: signals.append(f"超跌{chg_20d:.0f}%")

    return {
        "code": code,
        "name": STOCK_NAMES.get(code, "???"),
        "price": round(latest_price, 2),
        "score": round(score, 1),
        "rsi": round(rsi_now, 1) if not np.isnan(rsi_now) else None,
        "pe_pct": round(pe_pct, 1) if pe_pct is not None else None,
        "pb_pct": round(pb_pct, 1) if pb_pct is not None else None,
        "trend": trend,
        "macd_gap": round(macd_gap, 4),
        "chg_20d": round(chg_20d, 1),
        "signals": "; ".join(signals) if signals else "无特殊信号",
    }


def run():
    """扫描所有股票，输出TOP10推荐。"""
    cache_dir = ".cache"
    price_files = sorted([f for f in os.listdir(cache_dir) if f.startswith("prices_")])

    console.print()
    console.print(Panel.fit(
        f"正在扫描 {len(price_files)} 只股票，寻找最佳买入标的...",
        title=f"TOP10 买入推荐 — {date.today()}",
        border_style="cyan",
    ))

    results = []
    for pf in price_files:
        code = pf.replace("prices_", "").replace(".csv", "")
        # Skip ETFs
        if code in ("159915", "159919", "510050", "510300", "512100"):
            continue
        r = analyze_stock(code)
        if r:
            results.append(r)

    # Sort by score descending
    results.sort(key=lambda x: x["score"], reverse=True)

    # Display TOP 10
    console.print()
    table = Table(title="TOP 10 最值得买入股票")
    table.add_column("#", style="dim", width=3)
    table.add_column("代码", width=8)
    table.add_column("名称", width=10)
    table.add_column("现价", justify="right", width=8)
    table.add_column("评分", justify="right", width=6)
    table.add_column("RSI", justify="right", width=6)
    table.add_column("PE%", justify="right", width=6)
    table.add_column("PB%", justify="right", width=6)
    table.add_column("趋势", width=6)
    table.add_column("信号", width=30)

    for i, r in enumerate(results[:10]):
        color = "green" if r["score"] >= 70 else ("yellow" if r["score"] >= 55 else "red")
        pe_label = f"{r['pe_pct']:.0f}%" if r["pe_pct"] is not None else "-"
        pb_label = f"{r['pb_pct']:.0f}%" if r["pb_pct"] is not None else "-"
        rsi_str = f"{r['rsi']:.0f}" if r["rsi"] is not None else "-"
        trend_icon = "UP" if r["trend"] == "up" else ("DOWN" if r["trend"] == "down" else "SIDE")
        table.add_row(
            str(i + 1),
            r["code"],
            r["name"],
            f"{r['price']:.2f}",
            f"[{color}]{r['score']:.0f}[/{color}]",
            rsi_str,
            pe_label,
            pb_label,
            trend_icon,
            r["signals"],
        )

    console.print(table)

    # Score distribution
    console.print()
    high = [r for r in results if r["score"] >= 70]
    mid = [r for r in results if 55 <= r["score"] < 70]
    low = [r for r in results if r["score"] < 55]
    console.print(f"  强烈买入(>=70): {len(high)}只 | 建议买入(55-69): {len(mid)}只 | 观望(<55): {len(low)}只")
    console.print()

    # Detailed for TOP5
    console.print("[bold]TOP5 详细分析:[/bold]")
    console.print()
    for i, r in enumerate(results[:5]):
        console.print(f"  [bold cyan]#{i+1} {r['code']} {r['name']}[/bold cyan] — 评分 {r['score']:.0f}/100")
        console.print(f"    现价: {r['price']:.2f}元 | RSI: {r['rsi']:.0f} | PE分位: {pe_str(r)} | PB分位: {pb_str(r)} | 趋势: {r['trend']}")
        console.print(f"    20日涨跌: {r['chg_20d']:+.1f}% | MACD差距: {r['macd_gap']:.4f}")
        console.print(f"    信号: {r['signals']}")
        console.print()

    console.print("[dim]分析结果仅供参考，不构成投资建议。[/dim]")


def pe_str(r):
    return f"{r['pe_pct']:.0f}%" if r['pe_pct'] is not None else "-"

def pb_str(r):
    return f"{r['pb_pct']:.0f}%" if r['pb_pct'] is not None else "-"


if __name__ == "__main__":
    run()
