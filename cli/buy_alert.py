"""买入提醒 — 扫描全池，发现买入信号立即告警"""
import sys, io, os, numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from datetime import datetime

# ── Config ──
ALERT_THRESHOLD = 80       # 评分 >= 80 触发提醒
RSI_EXTREME = 20           # RSI <= 20 触发提醒
LOW_PROXIMITY = 3          # 距历史最低 <= 3% 触发提醒

# ── Known names ──
NAMES = {}
try:
    import akshare as ak
    df = ak.stock_info_a_code_name()
    for _, row in df.iterrows():
        NAMES[row['code']] = row['name']
except:
    pass
KNOWN = {
    '000001':'平安银行','000002':'万科A','000568':'泸州老窖','000596':'古井贡酒',
    '000625':'长安汽车','000858':'五粮液','002304':'洋河股份','300122':'智飞生物',
    '300498':'温氏股份','300760':'迈瑞医疗','600048':'保利发展','600085':'同仁堂',
    '600104':'上汽集团','600436':'片仔癀','600438':'通威股份','600585':'海螺水泥',
    '600720':'中交设计','600809':'山西汾酒','600845':'宝信软件','601238':'广汽集团',
    '603833':'欧派家居','688169':'石头科技','688271':'联影医疗','920802':'保丽洁',
    '002459':'晶澳科技','688223':'晶科能源','601012':'隆基绿能','002594':'比亚迪',
    '300529':'健帆生物','688036':'传音控股','002920':'德赛西威',
}
for k, v in KNOWN.items():
    if k not in NAMES:
        NAMES[k] = v

now = datetime.now()
print(f'=== 买入提醒扫描 === {now.strftime("%Y-%m-%d %H:%M")}')
print()

alerts = []
for f in sorted(os.listdir('.cache')):
    if not f.startswith('prices_'):
        continue
    code = f.replace('prices_', '').replace('.csv', '')
    if code in ('159915', '159919', '510050', '510300', '512100'):
        continue
    try:
        df = pd.read_csv(f'.cache/prices_{code}.csv', index_col=0, parse_dates=True)
        if len(df) < 50: continue
        close = df['close']
        cur = close.iloc[-1]
        all_high = df['high'].max()
        all_low = df['low'].min()
        from_low = (cur - all_low) / all_low * 100
        from_high = (cur / all_high - 1) * 100

        delta = close.diff()
        gain = delta.clip(lower=0); loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs)); rsi_now = rsi.iloc[-1]

        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        if ma20 > ma50 * 1.01: trend = 'UP'
        elif ma20 < ma50 * 0.99: trend = 'DN'
        else: trend = '--'

        chg_20d = (cur - close.iloc[-21]) / close.iloc[-21] * 100 if len(close) >= 21 else 0
        today_chg = (cur - close.iloc[-2]) / close.iloc[-2] * 100 if len(close) >= 2 else 0

        # Score
        score = 50
        if from_low < 3: score += 20
        elif from_low < 5: score += 16
        elif from_low < 10: score += 10
        elif from_low < 20: score += 5
        if rsi_now < 20: score += 18
        elif rsi_now < 25: score += 13
        elif rsi_now < 30: score += 9
        elif rsi_now < 35: score += 5
        if from_high < -60: score += 14
        elif from_high < -50: score += 10
        elif from_high < -40: score += 6
        if trend == 'UP': score += 8
        elif trend == '--': score += 4
        if chg_20d < -20: score += 6
        elif chg_20d < -15: score += 3
        score = min(100, score)

        # Alert conditions
        reasons = []
        if score >= ALERT_THRESHOLD:
            reasons.append(f'评分{score:.0f}')
        if rsi_now <= RSI_EXTREME:
            reasons.append(f'RSI{rsi_now:.0f}极度超卖')
        if from_low <= LOW_PROXIMITY:
            reasons.append(f'距历史最低仅{from_low:.0f}%')

        if reasons:
            alerts.append({
                'code': code,
                'name': NAMES.get(code, '???'),
                'cur': cur,
                'score': score,
                'rsi': rsi_now,
                'from_low': from_low,
                'from_high': from_high,
                'trend': trend,
                'today': today_chg,
                'reasons': ' | '.join(reasons),
            })
    except:
        pass

alerts.sort(key=lambda x: x['score'], reverse=True)

if not alerts:
    print('  当前无触发买入提醒的股票。')
    print(f'  阈值: 评分≥{ALERT_THRESHOLD} | RSI≤{RSI_EXTREME} | 距低≤{LOW_PROXIMITY}%')
else:
    # Group by urgency
    hot = [a for a in alerts if a['score'] >= 90]
    warm = [a for a in alerts if 80 <= a['score'] < 90]
    watch = [a for a in alerts if a['score'] < 80]

    if hot:
        print(f'🔥🔥 强烈买入提醒 ({len(hot)}只):')
        for a in hot:
            print(f'  {a["code"]} {a["name"]:<6}  {a["cur"]:.2f}元  评分{a["score"]:.0f}  RSI{a["rsi"]:.0f}  距低{a["from_low"]:.0f}%  {a["trend"]}  {a["reasons"]}')
        print()

    if warm:
        print(f'🟡 建议买入提醒 ({len(warm)}只):')
        for a in warm[:10]:
            print(f'  {a["code"]} {a["name"]:<6}  {a["cur"]:.2f}元  评分{a["score"]:.0f}  RSI{a["rsi"]:.0f}  距低{a["from_low"]:.0f}%  {a["trend"]}')
        print()

    if watch:
        print(f'🔵 关注级 ({len(watch)}只, RSI或距低触发):')
        for a in watch[:5]:
            print(f'  {a["code"]} {a["name"]:<6}  {a["cur"]:.2f}元  {a["reasons"]}')
        print()

    print(f'总计: {len(alerts)} 只触发提醒 | 扫描 {len([f for f in os.listdir(".cache") if f.startswith("prices_")])} 只')

print()
print('下次提醒: 交易时段每小时自动扫描')
