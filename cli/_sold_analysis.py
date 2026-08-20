"""已卖出股票分析 — 从 position_history 提取已清仓交易"""
import json, os, sys, io, ssl, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

POS_DIR = ".position_history"
trades = []

for f in sorted(os.listdir(POS_DIR)):
    if not f.endswith(".json"):
        continue
    path = os.path.join(POS_DIR, f)
    try:
        try:
            data = json.loads(open(path, "r", encoding="utf-8").read())
        except UnicodeDecodeError:
            data = json.loads(open(path, "r", encoding="gbk").read())
    except Exception:
        continue
    if not isinstance(data, dict):
        continue

    code = data.get("stock_code", "")
    entries = data.get("entries", [])
    adjusts = data.get("adjustments", [])

    buys = [e for e in entries if e.get("shares", 0) > 0]
    sells = [e for e in entries if e.get("shares", 0) < 0]
    if not sells:
        continue

    total_cost = sum(e.get("shares", 0) * e.get("price", 0) for e in buys)
    total_shares_bought = sum(e.get("shares", 0) for e in buys)

    total_sell_proceeds = sum(abs(e.get("shares", 0)) * e.get("price", 0) for e in sells)
    total_shares_sold = sum(abs(e.get("shares", 0)) for e in sells)

    sell_dates = [e.get("date", "") for e in sells]
    first_sell_date = min(sell_dates) if sell_dates else ""

    buy_adj = 0.0
    sell_adj = 0.0
    for a in adjusts:
        if not isinstance(a, dict):
            continue
        amt = a.get("amount", 0)
        adj_date = a.get("date", "")
        if adj_date and first_sell_date and adj_date >= first_sell_date:
            sell_adj += amt
        else:
            buy_adj += amt

    # effective_cost = buy_cost - buy_adjustments
    effective_cost = total_cost - buy_adj
    avg_cost = effective_cost / total_shares_bought if total_shares_bought > 0 else 0

    sold_portion_cost = effective_cost * total_shares_sold / total_shares_bought
    net_profit = total_sell_proceeds + sell_adj - sold_portion_cost
    pnl_pct = net_profit / sold_portion_cost * 100 if sold_portion_cost > 0 else 0

    buy_date = buys[0].get("date", "?") if buys else "?"
    sell_date = sells[-1].get("date", "?") if sells else "?"

    remaining = total_shares_bought - total_shares_sold
    status = "部分卖出" if remaining > 0 else "已清仓"

    name = data.get("stock_name", "")

    trades.append({
        "code": code, "name": name,
        "buy_date": buy_date, "sell_date": sell_date,
        "shares": total_shares_sold,
        "avg_cost": round(avg_cost, 2),
        "avg_sell": round(total_sell_proceeds / total_shares_sold, 2) if total_shares_sold > 0 else 0,
        "effective_cost": round(effective_cost, 2),
        "sold_portion_cost": round(sold_portion_cost, 2),
        "sell_proceeds": round(total_sell_proceeds, 2),
        "buy_adj": round(buy_adj, 2),
        "sell_adj": round(sell_adj, 2),
        "net_profit": round(net_profit, 2),
        "pnl_pct": round(pnl_pct, 2),
        "remaining": int(remaining),
        "status": status,
    })

if not trades:
    print("暂无已卖出记录")
    sys.exit(0)

trades.sort(key=lambda x: x["sell_date"], reverse=True)

# Get names from realtime API
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
codes_need_name = [t["code"] for t in trades if not t["name"]]
if codes_need_name:
    items = []
    for c in codes_need_name:
        pfx = "nq" if c.startswith(("9", "8")) else ("sz" if c.startswith(("0", "3")) else "sh")
        items.append(f"{pfx}{c}")
    try:
        url = f'https://qt.gtimg.cn/q={",".join(items)}'
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=10, context=ctx).read().decode("gbk", errors="replace")
        for line in raw.split("\n"):
            if "~" not in line or "none_match" in line:
                continue
            p = line.split("~")
            if len(p) < 4:
                continue
            rh = p[0]
            code_raw = ""
            for ch in rh:
                if ch.isdigit():
                    code_raw += ch
                elif code_raw:
                    break
            cd = code_raw[-6:] if len(code_raw) >= 6 else code_raw
            for t in trades:
                if t["code"] == cd:
                    t["name"] = p[1].strip()
    except Exception:
        pass

total_profit = sum(t["net_profit"] for t in trades)
wins = sum(1 for t in trades if t["net_profit"] > 0)
losses = sum(1 for t in trades if t["net_profit"] < 0)

print("=" * 105)
print("  \U0001f4ca 已卖出股票分析")
print("=" * 105)
print(f'  {"代码":<8} {"名称":<8} {"买入日":<12} {"卖出日":<12} {"股数":>5} {"均价":>7} {"卖价":>7} {"盈利":>9} {"盈%":>7} {"状态":<8}')
print("-" * 105)

for t in trades:
    bar = "\U0001f534" if t["pnl_pct"] > 25 else ("\U0001f7e0" if t["pnl_pct"] > 10 else ("\U0001f7e2" if t["pnl_pct"] > 0 else "⚪"))
    print(f'  {bar} {t["code"]:<8} {t["name"]:<8} {t["buy_date"]:<12} {t["sell_date"]:<12} {t["shares"]:>5} {t["avg_cost"]:>7.2f} {t["avg_sell"]:>7.2f} {t["net_profit"]:>+9.2f} {t["pnl_pct"]:>+6.1f}% {t["status"]:<8}')

print("-" * 105)
print(f'  {"合计":<8} {"":<8} {"":<12} {"":<12} {"":>5} {"":<7} {"":<7} {total_profit:>+9.2f}')

print()
print(f"  \U0001f4c8 交易统计")
print(f"  总交易: {len(trades)} 笔 | 盈利: {wins} 笔 | 亏损: {losses} 笔 | 胜率: {wins/len(trades)*100:.0f}%")
print(f"  累计盈亏: {total_profit:+.2f}元")
if wins > 0:
    avg_win = sum(t["net_profit"] for t in trades if t["net_profit"] > 0) / wins
    print(f"  平均盈利: +{avg_win:.0f}元")
if losses > 0:
    avg_loss = sum(t["net_profit"] for t in trades if t["net_profit"] < 0) / losses
    print(f"  平均亏损: {avg_loss:.0f}元")

print()
for t in trades:
    print(f"  \U0001f4dd {t['code']} {t['name']}:")
    print(f"     买入成本 {t['effective_cost']:.2f}元 (买入价{t['avg_cost']:.2f}x{t['shares']}股, 股息/费用调整{t['buy_adj']:+.2f})")
    print(f"     卖出收入 {t['sell_proceeds']:.2f}元 (@{t['avg_sell']:.2f}), 卖出费用 {t['sell_adj']:+.2f}")
    print(f"     ✅ 净利润 {t['net_profit']:+.2f}元 ({t['pnl_pct']:+.1f}%)")

# Summary
all_json = set(f.replace(".json", "") for f in os.listdir(POS_DIR) if f.endswith(".json") and f != "portfolio_snapshots.json")
sold_codes = set(t["code"] for t in trades)
holding_codes = set()
for f in os.listdir(POS_DIR):
    if not f.endswith(".json") or f == "portfolio_snapshots.json":
        continue
    try:
        try:
            d = json.loads(open(os.path.join(POS_DIR, f), "r", encoding="utf-8").read())
        except UnicodeDecodeError:
            d = json.loads(open(os.path.join(POS_DIR, f), "r", encoding="gbk").read())
    except Exception:
        continue
    if not isinstance(d, dict):
        continue
    ts = sum(e.get("shares", 0) for e in d.get("entries", []))
    if ts > 0:
        holding_codes.add(d.get("stock_code", ""))

print()
print(f"  当前持仓: {len(holding_codes)}只 | 已清仓: {len(sold_codes)}只 | 总计追踪: {len(holding_codes | sold_codes)}只")
print()
print("  ⚠️ 以上为历史交易记录，不构成投资建议。")
