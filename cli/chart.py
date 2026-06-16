"""下午预测曲线 — 概率分布 + 置信区间可视化。"""
import io, sys, math
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from core.data_fetcher import fetch_normalized_data, fetch_realtime_quote
from core.analyzers.technical import analyze as at
from core.market_context import get_market_regime, market_range_multiplier
from core.prediction_tracker import get_calibration


def norm_pdf(x, mu, sigma):
    """正态分布概率密度。"""
    return math.exp(-0.5 * ((x - mu) / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))


def run():
    data = fetch_normalized_data("002594", force_refresh=False)
    prices = data.prices

    try:
        rt = fetch_realtime_quote("002594")
        cur_price = rt.get("f43", 0) / 100
    except Exception:
        cur_price = prices[-1].close

    _saved = sys.stdout
    sys.stdout = io.StringIO()
    result = at(data)
    sys.stdout = _saved

    momentum = 0.0
    if len(prices) >= 4:
        momentum = (
            (prices[-1].close - prices[-2].close) * 0.5
            + (prices[-2].close - prices[-3].close) * 0.3
            + (prices[-3].close - prices[-4].close) * 0.2
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

    cal = get_calibration("002594")
    market = get_market_regime()
    mkt_mult = market_range_multiplier(market)
    atr_range = (result.atr_14 or 0) * 0.6 * mkt_mult

    pred_close = cur_price + momentum * 0.3 + ma_bias + rsi_bias + cal.get("bias_correction", 0.0)
    pred_low = pred_close - atr_range
    pred_high = pred_close + atr_range

    # 标准差 = ATR_range / 2 (区间约覆盖 95% -> 2 sigma)
    sigma = atr_range / 2

    # 生成概率分布曲线
    chart_width = 55
    price_min = pred_low - sigma * 0.5
    price_max = pred_high + sigma * 0.5

    x_vals = [price_min + (price_max - price_min) * i / (chart_width - 1) for i in range(chart_width)]
    y_vals = [norm_pdf(x, pred_close, sigma) for x in x_vals]
    y_max = max(y_vals)

    # 置信区间界线
    ci68_low = pred_close - sigma
    ci68_high = pred_close + sigma
    ci95_low = pred_close - sigma * 2
    ci95_high = pred_close + sigma * 2

    print()
    print("=" * 72)
    print("  比亚迪 002594  下午收盘预测  概率分布曲线")
    print("=" * 72)
    print()

    # 顶部概率标尺
    print("  概率")
    print("  密度")
    for level_pct in [100, 75, 50, 25]:
        level = y_max * level_pct / 100
        print("  {:4.0f}% |".format(level_pct), end="")
        for i, y in enumerate(y_vals):
            if y >= level:
                if level_pct >= 90:
                    print("█", end="")
                elif level_pct >= 60:
                    print("▓", end="")
                elif level_pct >= 30:
                    print("▒", end="")
                else:
                    print("░", end="")
            else:
                # 检查是否在68%置信区间内
                x = x_vals[i]
                if ci68_low <= x <= ci68_high:
                    print("·", end="")
                elif ci95_low <= x <= ci95_high:
                    print(" ", end="")
                else:
                    print(" ", end="")
        print()

    # 价格轴
    print("      |" + "-" * chart_width)
    print("      |", end="")
    # 标注关键价格
    ticks = []
    for lbl, val in [
        ("L={:.2f}".format(pred_low), pred_low),
        ("现={:.2f}".format(cur_price), cur_price),
        ("预={:.2f}".format(pred_close), pred_close),
        ("H={:.2f}".format(pred_high), pred_high),
    ]:
        pos = int((val - price_min) / (price_max - price_min) * (chart_width - 1))
        ticks.append((pos, lbl))

    last_pos = 0
    for pos, lbl in sorted(ticks):
        print(" " * (pos - last_pos), end="")
        print("|", end="")
        last_pos = pos + 1
    print()

    # 标签行
    print("      ", end="")
    last_pos = 0
    for pos, lbl in sorted(ticks):
        print(" " * max(0, pos - last_pos), end="")
        print(lbl, end="")
        last_pos = pos + len(lbl)
    print()

    print()
    print("  " + "-" * 66)
    print("  图例:  ██ 高概率区(90%+)  ▓▓ 中高概率(60%+)  ▒▒ 中等(30%+)  ░░ 低概率")
    print("         ·· 68%置信区间内  [空格] 95%置信区间内")
    print()

    # 置信区间说明
    print("  " + "=" * 66)
    print("  {:^66}".format("置信区间"))
    print("  " + "-" * 66)
    print("  {:16} {:>16} {:>16} {:>10}".format("", "下限", "上限", "概率"))
    print("  " + "-" * 66)
    print("  {:16} {:>15.2f} {:>15.2f} {:>9.0f}%".format("68% (1σ)", ci68_low, ci68_high, 68))
    print("  {:16} {:>15.2f} {:>15.2f} {:>9.0f}%".format("95% (2σ)", ci95_low, ci95_high, 95))
    print("  {:16} {:>15.2f} {:>15.2f} {:>9.0f}%".format("预测区间(ATR)", pred_low, pred_high, 95))
    print("  " + "-" * 66)
    print()

    # 下午时段分析
    print("  " + "=" * 66)
    print("  {:^66}".format("下午走势预判"))
    print("  " + "-" * 66)

    # 午盘区间通常更窄（成交量下降）
    afternoon_range = atr_range * 0.45
    afternoon_low = cur_price - afternoon_range
    afternoon_high = cur_price + afternoon_range

    direction = "偏多 ↑" if pred_close > cur_price else ("偏空 ↓" if pred_close < cur_price else "平盘 →")
    print("  上午收盘价: {:.2f}".format(cur_price))
    print("  下午预测区间: {:.2f} ~ {:.2f}  (宽度 {:.2f}元)".format(afternoon_low, afternoon_high, afternoon_range * 2))
    print("  方向: {}".format(direction))
    print()

    # 下午概率条
    width2 = 55
    p_low2 = afternoon_low - sigma * 0.3
    p_high2 = afternoon_high + sigma * 0.3
    x2 = [p_low2 + (p_high2 - p_low2) * i / (width2 - 1) for i in range(width2)]
    y2 = [norm_pdf(x, pred_close, sigma * 0.7) for x in x2]
    ym2 = max(y2)

    print("  下午概率分布:")
    print("  " + "-" * width2)
    for level_pct in [80, 50, 20]:
        level = ym2 * level_pct / 100
        print("  {:3.0f}%|".format(level_pct), end="")
        for i, y in enumerate(y2):
            print("█" if y >= level else " ", end="")
        print()
    print("  " + "-" * width2)
    print("  {:>6.2f}{:>49}{:.2f}".format(afternoon_low, " ", afternoon_high))
    print("       {:^6.2f}       {:^6.2f}".format(cur_price, pred_close))
    print("       现价               预测")

    print()
    print("  " + "=" * 66)
    print("  预测模型因子")
    print("  {:20} {:>10}".format("动量(3日加权)", "{:+.3f}".format(momentum)))
    print("  {:20} {:>10}".format("MA均值回归", "{:+.3f}".format(ma_bias)))
    print("  {:20} {:>10}".format("RSI修正", "{:+.3f}".format(rsi_bias)))
    print("  {:20} {:>10}".format("校准偏差({}次)".format(cal.get("based_on", 0)), "{:+.3f}".format(cal.get("bias_correction", 0))))
    print("  {:20} {:>10}".format("大盘乘数", "x{:.1f}".format(mkt_mult)))
    print("  {:20} {:>10}".format("预测变动", "{:+.3f}元".format(pred_close - cur_price)))
    print("  " + "=" * 66)
    print()


if __name__ == "__main__":
    run()
