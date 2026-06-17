"""大盘趋势预测 — 上证50ETF(510050)代理 + 曲线图。"""
import sys, io, math
import numpy as np
import pandas as pd
from datetime import date, datetime, timedelta

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def run():
    # ── 加载数据 ──────────────────────────────────────────
    df = pd.read_csv(".cache/prices_510050.csv", index_col=0, parse_dates=True)
    close = df["close"].iloc[-60:]
    high = df["high"].iloc[-60:]
    low = df["low"].iloc[-60:]
    vol = df["volume"].iloc[-60:]
    n = len(close)

    latest_price = close.iloc[-1]
    latest_date = close.index[-1]

    # ── 技术指标 ──────────────────────────────────────────
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_hist = (dif - dea) * 2

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # KDJ
    low_n = close.rolling(9).min()
    high_n = close.rolling(9).max()
    rsv = (close - low_n) / (high_n - low_n + 0.0001) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d

    # ── 市场判定 (6因子投票) ──────────────────────────────
    today_chg = (close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100
    mom5 = (close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100 if n >= 6 else 0
    mom10 = (close.iloc[-1] - close.iloc[-11]) / close.iloc[-11] * 100 if n >= 11 else 0
    up_ratio = sum(1 for i in range(-10, 0) if close.iloc[i] > close.iloc[i-1]) / 10 * 100

    bear_score = 0
    bull_score = 0

    if ma20.iloc[-1] > ma50.iloc[-1] * 1.01: bull_score += 3
    elif ma20.iloc[-1] < ma50.iloc[-1] * 0.99: bear_score += 3

    if today_chg > 0.8: bull_score += 4
    elif today_chg > 0.3: bull_score += 2
    elif today_chg < -0.8: bear_score += 4
    elif today_chg < -0.3: bear_score += 2

    if mom5 > 3: bull_score += 2
    elif mom5 < -3: bear_score += 2

    if mom10 > 4: bull_score += 1
    elif mom10 < -4: bear_score += 1

    if rsi.iloc[-1] > 60: bull_score += 1
    elif rsi.iloc[-1] < 40: bear_score += 1

    if up_ratio > 65: bull_score += 1
    elif up_ratio < 35: bear_score += 1

    if bull_score >= bear_score + 2:
        regime = "牛市"
        regime_en = "BULL"
    elif bear_score >= bull_score + 2:
        regime = "熊市"
        regime_en = "BEAR"
    else:
        regime = "震荡"
        regime_en = "SIDEWAYS"

    # ── 今日预测 ──────────────────────────────────────────
    momentum = (close.iloc[-1] - close.iloc[-2]) * 0.5 + (close.iloc[-2] - close.iloc[-3]) * 0.3

    # 方向概率
    up_votes = sum([
        1 if today_chg > -0.2 else 0,       # 今日跌幅不大
        1 if mom5 > -2 else 0,               # 短期动量还可以
        1 if rsi.iloc[-1] < 70 else 0,       # 未超买
        1 if up_ratio > 40 else 0,           # 涨跌比接近50%
        1 if macd_hist.iloc[-1] > macd_hist.iloc[-2] else 0,  # MACD柱缩短(空方减弱)
    ])
    down_votes = 5 - up_votes

    pred_dir = "UP" if up_votes > down_votes else ("DOWN" if down_votes > up_votes else "FLAT")
    confidence = max(up_votes, down_votes) / 5 * 100

    # 预测区间
    atr = (high - low).rolling(14).mean().iloc[-1]
    pred_high = latest_price + atr * 0.8
    pred_low = latest_price - atr * 0.6
    pred_close = latest_price + momentum * 0.4

    # ── 输出 ──────────────────────────────────────────────
    console.print()
    console.print(Panel.fit(
        f"上证50ETF (510050) — 大盘代理\n数据: {close.index[0].date()} ~ {latest_date.date()} ({n}交易日)",
        title=f"大盘趋势预测 — {date.today()}",
        border_style="cyan",
    ))

    # 头部
    color = "green" if regime_en == "BULL" else ("red" if regime_en == "BEAR" else "yellow")
    console.print(Panel(
        f"[bold {color}]{regime} ({regime_en})[/bold {color}]\n"
        f"牛熊比分: 牛{bull_score} vs 熊{bear_score}\n"
        f"今日方向: {'↑' if pred_dir == 'UP' else '↓' if pred_dir == 'DOWN' else '→'} {pred_dir} ({confidence:.0f}%置信)",
        border_style=color,
    ))
    console.print()

    # ── Panel 1: 价格曲线 ───────────────────────────────
    console.print("[bold][1] K线区域 + 均线  (近60日)[/bold]")
    W = 74
    H = 10

    all_vals = list(close.values) + list(ma20.dropna().values) + list(ma50.dropna().values)
    vmin = min(all_vals) * 0.98
    vmax = max(all_vals) * 1.02
    vr = vmax - vmin

    pv = close.values
    m20v = ma20.values
    m50v = ma50.values

    for row in range(H - 1, -1, -1):
        level = vmin + vr * row / (H - 1)
        line = ""
        for col in range(W):
            idx = int(col * n / W)
            if idx >= n: idx = n - 1
            px = pv[idx]
            m20x = m20v[idx]
            m50x = m50v[idx]

            char = " "
            if not np.isnan(px) and abs(px - level) < vr * 0.025:
                char = "o"
            if not np.isnan(m20x) and abs(m20x - level) < vr * 0.02:
                char = "2" if char == " " else char
            if not np.isnan(m50x) and abs(m50x - level) < vr * 0.02:
                char = "5" if char in (" ", "o", "2") else char
            line += char
        console.print(f"  {line}")

    console.print(f"  {vmin:>6.2f}" + " " * (W - 14) + f"{vmax:>6.2f}")
    console.print(f"  o=价格  2=MA20({ma20.iloc[-1]:.2f})  5=MA50({ma50.iloc[-1]:.2f})")
    console.print()

    # ── Panel 2: MACD ────────────────────────────────────
    console.print("[bold][2] MACD 指标  (近60日)[/bold]")

    dv = dif.iloc[-60:].values
    ev = dea.iloc[-60:].values
    hv = macd_hist.iloc[-60:].values
    nd = len(dv)
    dmin = min(min(dv), min(ev), min(hv)) * 1.1
    dmax = max(max(dv), max(ev), max(hv)) * 1.1
    dr = dmax - dmin
    if dr == 0: dr = 1
    zero_r = int((0 - dmin) / dr * (H - 1))
    zero_r = max(0, min(H - 1, zero_r))

    for row in range(H - 1, -1, -1):
        level = dmin + dr * row / (H - 1)
        line = ""
        for col in range(W):
            idx = int(col * nd / W)
            if idx >= nd: idx = nd - 1
            dx = dv[idx]; ex = ev[idx]; hx = hv[idx]
            char = " "
            if row == zero_r: char = "-"
            if not np.isnan(dx) and abs(dx - level) < dr * 0.025: char = "D"
            if not np.isnan(ex) and abs(ex - level) < dr * 0.025: char = "E" if char in (" ", "-") else char
            if not np.isnan(hx):
                if hx > 0 and 0 < level < hx: char = "|" if char in (" ", "-") else char
                elif hx < 0 and hx < level < 0: char = ":" if char in (" ", "-") else char
            line += char
        console.print(f"  {line}")
    console.print(f"  DIF={dif.iloc[-1]:.4f}  DEA={dea.iloc[-1]:.4f}  MACD柱={macd_hist.iloc[-1]:.4f}  |  --- 零轴")
    macd_state = "多头 (DIF>DEA)" if dif.iloc[-1] > dea.iloc[-1] else ("收敛中" if macd_hist.iloc[-1] > macd_hist.iloc[-2] else "空头扩大")
    console.print(f"  MACD状态: {macd_state}")
    console.print()

    # ── Panel 3: RSI + KDJ ───────────────────────────────
    console.print("[bold][3] RSI(14) + KDJ 指标[/bold]")
    H2 = 6
    rv = rsi.iloc[-60:].values
    kv = k.iloc[-60:].values
    dvk = d.iloc[-60:].values

    for row in range(H2 - 1, -1, -1):
        level = 100 * row / (H2 - 1)
        line = ""
        for col in range(W):
            idx = int(col * 60 / W)
            if idx >= 60: idx = 59
            rx = rv[idx] if idx < len(rv) else np.nan
            kx = kv[idx] if idx < len(kv) else np.nan
            if not np.isnan(rx):
                rx_r = int(rx / 100 * (H2 - 1))
                if rx_r == row: line += "R"
                elif rx_r > row: line += "|"
                else: line += " "
            else:
                line += " "
            # KDJ-K mark
            if not np.isnan(kx) and idx == len(kv) - 1:
                kx_r = int(kx / 100 * (H2 - 1))
                if kx_r == row and line[-1] == " ": line = line[:-1] + "K"
        if row == int(0.7 * (H2 - 1)):
            console.print(f"  {'-'*W}  超买线 70")
        elif row == int(0.3 * (H2 - 1)):
            console.print(f"  {'-'*W}  超卖线 30")
        else:
            console.print(f"  {line}")

    console.print(f"  RSI(14)={rsi.iloc[-1]:.1f}  |  K={k.iloc[-1]:.1f}  D={d.iloc[-1]:.1f}  J={j.iloc[-1]:.1f}")
    rsi_state = "超卖 (反弹概率高)" if rsi.iloc[-1] < 30 else ("超买 (回调风险)" if rsi.iloc[-1] > 70 else "中性")
    console.print(f"  RSI状态: {rsi_state}")
    console.print()

    # ── Panel 4: 预测 + 决策 ──────────────────────────────
    console.print("[bold][4] 今日大盘预测 + 决策[/bold]")
    console.print()

    table = Table(title="多因子投票判定")
    table.add_column("因子", style="cyan")
    table.add_column("信号", width=30)
    table.add_column("方向")

    factors = [
        ("MA20 vs MA50", f"MA20={ma20.iloc[-1]:.2f}  MA50={ma50.iloc[-1]:.2f}",
         "牛" if ma20.iloc[-1] > ma50.iloc[-1] * 1.01 else ("熊" if ma20.iloc[-1] < ma50.iloc[-1] * 0.99 else "平")),
        ("今日涨跌", f"{today_chg:+.2f}%",
         "牛" if today_chg > 0.3 else ("熊" if today_chg < -0.3 else "平")),
        ("5日动量", f"{mom5:+.2f}%",
         "牛" if mom5 > 3 else ("熊" if mom5 < -3 else "平")),
        ("10日动量", f"{mom10:+.2f}%",
         "牛" if mom10 > 4 else ("熊" if mom10 < -4 else "平")),
        ("RSI(14)", f"{rsi.iloc[-1]:.1f}",
         "牛" if rsi.iloc[-1] > 60 else ("熊" if rsi.iloc[-1] < 40 else "平")),
        ("涨跌比", f"{up_ratio:.0f}% (近10日)",
         "牛" if up_ratio > 65 else ("熊" if up_ratio < 35 else "平")),
    ]
    for name, sig, dire in factors:
        icon = "🟢" if dire == "牛" else ("🔴" if dire == "熊" else "⚪")
        table.add_row(name, sig, f"{icon} {dire}")

    table.add_section()
    table.add_row("[bold]总计[/bold]", "", f"[bold]牛 {bull_score} : 熊 {bear_score}[/bold]")

    console.print(table)
    console.print()

    console.print(f"[bold]今日预测:[/bold]")
    console.print(f"  最新价:   {latest_price:.3f}")
    console.print(f"  方向:     {'↑ 看涨' if pred_dir == 'UP' else '↓ 看跌' if pred_dir == 'DOWN' else '→ 平盘'} ({confidence:.0f}%置信)")
    console.print(f"  预测高:   {pred_high:.3f}")
    console.print(f"  预测低:   {pred_low:.3f}")
    console.print(f"  最可能:   {pred_close:.3f} (收盘)")
    console.print()

    if regime_en == "BEAR":
        console.print(f"  [red]市场处于熊市 → 个股评分 -8 → 预测区间 ×1.3放宽[/red]")
    elif regime_en == "BULL":
        console.print(f"  [green]市场处于牛市 → 个股评分 +5 → 预测区间 ×0.9收窄[/green]")

    console.print()
    console.print(f"  [dim]分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}  仅供参考，不构成投资建议[/dim]")


if __name__ == "__main__":
    run()
