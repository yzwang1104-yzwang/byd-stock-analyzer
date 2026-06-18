"""10倍潜力股筛选 — 找能翻5-10倍的黑马，不是找便宜的蓝筹"""
import sys, io, os, numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

NAMES = {
    '002007':'华兰生物','002044':'美年健康','002074':'国轩高科','002129':'中环股份',
    '002202':'金风科技','002236':'大华股份','002271':'东方雨虹','002311':'海大集团',
    '002384':'东山精密','002459':'晶澳科技','002460':'赣锋锂业','002466':'天齐锂业',
    '002493':'荣盛石化','002600':'领益智造','002648':'卫星化学','002709':'天赐材料',
    '002714':'牧原股份','002812':'恩捷股份','002916':'深南电路','002920':'德赛西威',
    '300014':'亿纬锂能','300024':'机器人','300033':'同花顺','300059':'东方财富',
    '300122':'智飞生物','300136':'信维通信','300142':'沃森生物','300207':'欣旺达',
    '300274':'阳光电源','300308':'中际旭创','300316':'晶盛机电','300347':'泰格医药',
    '300394':'天孚通信','300408':'三环集团','300433':'蓝思科技','300450':'先导智能',
    '300502':'新易盛','300529':'健帆生物','300628':'亿联网络','300661':'圣邦股份',
    '300763':'锦浪科技','600048':'保利发展','600161':'天坛生物','600233':'圆通速递',
    '600298':'安琪酵母','600370':'*ST三房','600406':'国电南瑞','600415':'小商品城',
    '600426':'华鲁恒升','600436':'片仔癀','600438':'通威股份','600460':'士兰微',
    '600482':'中国动力','600489':'中金黄金','600547':'山东黄金','600567':'山鹰国际',
    '600588':'用友网络','600660':'福耀玻璃','600699':'均胜电子','600703':'三安光电',
    '600745':'闻泰科技','600754':'锦江酒店','600809':'山西汾酒','600845':'宝信软件',
    '600893':'航发动力','601021':'春秋航空','601100':'恒立液压','601127':'赛力斯',
    '601615':'明阳智能','601689':'拓普集团','603259':'药明康德','603288':'海天味业',
    '603501':'韦尔股份','603799':'华友钴业','603993':'洛阳钼业',
    '688005':'容百科技','688008':'澜起科技','688012':'中微公司','688036':'传音控股',
    '688041':'海光信息','688111':'金山办公','688126':'沪硅产业','688169':'石头科技',
    '688185':'康希诺','688187':'时代电气','688223':'晶科能源','688256':'寒武纪',
    '688271':'联影医疗','688347':'华虹公司','688390':'固德威','688396':'华润微',
    '688472':'阿特斯','688561':'奇安信','688599':'天合光能','688608':'恒玄科技',
    '688728':'格科微','688777':'中控技术','688819':'天能股份','688981':'中芯国际',
    '830832':'齐鲁华信','830879':'基康仪器','920802':'春光智能','920809':'云星科技',
    '920832':'齐鲁华信','920839':'万通液压',
}

results = []
for f in sorted(os.listdir('.cache')):
    if not f.startswith('prices_'): continue
    code = f.replace('prices_','').replace('.csv','')
    if code in ('159915','159919','510050','510300','512100'): continue

    try:
        df = pd.read_csv(f'.cache/prices_{code}.csv', index_col=0, parse_dates=True)
        if len(df) < 50: continue
        closes = df['close'].values
        cur = closes[-1]

        # PE
        pe = 0
        valf = f'.cache/valuation_{code}.csv'
        if os.path.exists(valf):
            vdf = pd.read_csv(valf, index_col=0)
            if 'current_pe' in vdf.columns:
                pe = float(vdf['current_pe'].iloc[-1]) if len(vdf)>0 else 0

        # Historical low
        low_all = min(closes)
        from_low = (cur - low_all) / low_all * 100  # 距历史最低的涨幅

        # Changes
        chg_20d = (cur-closes[-21])/closes[-21]*100 if len(closes)>=21 else 0
        chg_3d = (cur-closes[-4])/closes[-4]*100 if len(closes)>=4 else 0
        chg_5d = (cur-closes[-6])/closes[-6]*100 if len(closes)>=6 else 0

        # ATR%
        trs = []
        for i in range(-20,0):
            h = float(df.iloc[i]['high']) if 'high' in df.columns else closes[i]
            l = float(df.iloc[i]['low']) if 'low' in df.columns else closes[i]
            tr = max(h-l, abs(h-closes[i-1]), abs(l-closes[i-1]))
            trs.append(tr)
        atr_pct = np.mean(trs)/cur*100

        # RSI
        deltas = np.diff(closes[-15:])
        g = np.where(deltas>0,deltas,0); lo = np.where(deltas<0,-deltas,0)
        rsi = 100-100/(1+np.mean(g)/np.mean(lo)) if np.mean(lo)>0 else 50

        # Trend
        ma20=np.mean(closes[-20:]); ma50=np.mean(closes[-50:]) if len(closes)>=50 else ma20
        if ma20>ma50*1.01: trend='↑'
        elif ma20<ma50*0.99: trend='↓'
        else: trend='→'

        mom_accel = chg_3d - chg_5d
        reversal = chg_3d > -2 and mom_accel > -1

        # === 10倍潜力评分 ===
        score = 50
        # 超跌 = 翻倍空间
        if chg_20d < -40: score += 30
        elif chg_20d < -30: score += 22
        elif chg_20d < -20: score += 15
        elif chg_20d < -10: score += 8
        # 高波动 = 爆发力
        if atr_pct > 5: score += 15
        elif atr_pct > 4: score += 12
        elif atr_pct > 3: score += 8
        elif atr_pct > 2: score += 4
        # 动量反转
        if reversal and chg_3d > 2: score += 15
        elif reversal and chg_3d > -1: score += 10
        elif reversal: score += 5
        # RSI极端
        if rsi < 20: score += 10
        elif rsi < 25: score += 7
        elif rsi < 30: score += 4
        # PE安全
        if 0 < pe < 15: score += 8
        elif 0 < pe < 25: score += 4
        # 趋势
        if trend == '↑': score += 5
        # 亏损惩罚
        if pe < 0 or pe > 50: score -= 10
        # 今日强度
        td = (cur-closes[-2])/closes[-2]*100
        if td > 3: score += 5
        elif td > 1: score += 3
        elif td < -3: score -= 5

        score = max(0, min(100, score))
        if score >= 50:
            results.append({
                'code':code,'name':NAMES.get(code,'??'),'price':cur,
                'score':score,'chg_20d':chg_20d,'chg_3d':chg_3d,
                'rsi':rsi,'atr_pct':atr_pct,'pe':pe,
                'trend':trend,'reversal':reversal,'today':td,
                'low_all':low_all,'from_low':from_low,
            })
    except: pass

results.sort(key=lambda x: x['score'], reverse=True)

print(f'{"#":<3} {"代码":<8} {"名称":<8} {"现价":>7} {"潜力分":>4} {"最低":>7} {"距低":>6} {"20日":>7} {"3日":>6} {"RSI":>5} {"ATR%":>5} {"PE":>6} {"趋":<2}  {"翻倍信号"}')
print('='*115)
for i, r in enumerate(results[:25]):
    t = '↑' if r['trend']=='↑' else ('↓' if r['trend']=='↓' else '→')
    rev = '🔄' if r['reversal'] else ''
    td_str = f'今{r["today"]:+.0f}%' if abs(r['today'])>1 else ''
    sig = []
    if r['chg_20d'] < -25: sig.append('💥深跌')
    elif r['chg_20d'] < -15: sig.append('📉超跌')
    if r['atr_pct'] > 4: sig.append('🚀高爆')
    if r['reversal'] and r['chg_3d'] > 1: sig.append('🔑已反弹')
    if r['rsi'] < 25: sig.append('⚡极端')
    if 0 < r['pe'] < 15: sig.append('💰低PE')
    sig_str = ' '.join(sig)
    from_low_str = f'+{r["from_low"]:.0f}%' if r['from_low'] > 5 else f'‼️+{r["from_low"]:.0f}%'
    print(f'{i+1:<3} {r["code"]:<8} {r["name"]:<8} {r["price"]:>7.2f} {r["score"]:>4.0f} {r["low_all"]:>7.2f} {from_low_str:>6} {r["chg_20d"]:>+6.0f}% {r["chg_3d"]:>+5.0f}% {r["rsi"]:>5.0f} {r["atr_pct"]:>4.1f}% {r["pe"]:>6.0f} {t:<2}  {sig_str} {rev} {td_str}')

print(f'\n{'='*100}')
print(f'共{len(results)}只有翻倍潜力 | 评分=超跌幅度+波动爆发力+反转信号+PE安全垫')
