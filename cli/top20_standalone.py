import os, sys, io, csv
import numpy as np
import pandas as pd

# 必须最先重定向
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

STOCK_NAMES = {
    "000001":"平安银行","000002":"万科A","000021":"深科技","000063":"中兴通讯",
    "000100":"TCL科技","000157":"中联重科","000333":"美的集团","000338":"潍柴动力",
    "000425":"徐工机械","000538":"云南白药","000568":"泸州老窖","000596":"古井贡酒",
    "000625":"长安汽车","000651":"格力电器","000725":"京东方A","000768":"中航西飞",
    "000776":"广发证券","000800":"一汽解放","000807":"云铝股份","000858":"五粮液",
    "000895":"双汇发展","000977":"浪潮信息","001979":"招商蛇口","002007":"华兰生物",
    "002027":"分众传媒","002044":"美年健康","002049":"紫光国微","002050":"三花智控",
    "002074":"国轩高科","002129":"中环股份","002142":"宁波银行","002179":"中航光电",
    "002202":"金风科技","002230":"科大讯飞","002236":"大华股份","002241":"歌尔股份",
    "002271":"东方雨虹","002304":"洋河股份","002311":"海大集团","002352":"顺丰控股",
    "002371":"北方华创","002384":"东山精密","002415":"海康威视","002459":"晶澳科技",
    "002460":"赣锋锂业","002466":"天齐锂业","002475":"立讯精密","002493":"荣盛石化",
    "002594":"比亚迪","002600":"领益智造","002625":"光启技术","002648":"卫星化学",
    "002709":"天赐材料","002714":"牧原股份","002812":"恩捷股份","002916":"深南电路",
    "002920":"德赛西威","300014":"亿纬锂能","300024":"机器人","300033":"同花顺",
    "300059":"东方财富","300122":"智飞生物","300124":"汇川技术","300136":"信维通信",
    "300142":"沃森生物","300207":"欣旺达","300274":"阳光电源","300308":"中际旭创",
    "300316":"晶盛机电","300347":"泰格医药","300394":"天孚通信","300408":"三环集团",
    "300433":"蓝思科技","300450":"先导智能","300498":"温氏股份","300502":"新易盛",
    "300529":"健帆生物","300628":"亿联网络","300661":"圣邦股份","300750":"宁德时代",
    "300760":"迈瑞医疗","300763":"锦浪科技","600000":"浦发银行","600019":"宝钢股份",
    "600028":"中国石化","600029":"南方航空","600030":"中信证券","600031":"三一重工",
    "600036":"招商银行","600048":"保利发展","600085":"同仁堂","600104":"上汽集团",
    "600111":"北方稀土","600150":"中国船舶","600161":"天坛生物","600176":"中国巨石",
    "600188":"兖矿能源","600196":"复星医药","600233":"圆通速递","600276":"恒瑞医药",
    "600298":"安琪酵母","600309":"万华化学","600346":"恒力石化","600370":"*ST三房",
    "600406":"国电南瑞","600415":"小商品城","600426":"华鲁恒升","600436":"片仔癀",
    "600438":"通威股份","600460":"士兰微","600482":"中国动力","600489":"中金黄金",
    "600519":"贵州茅台","600547":"山东黄金","600567":"山鹰国际","600585":"海螺水泥",
    "600588":"用友网络","600660":"福耀玻璃","600690":"海尔智家","600699":"均胜电子",
    "600703":"三安光电","600745":"闻泰科技","600754":"锦江酒店","600760":"中航沈飞",
    "600795":"国电电力","600809":"山西汾酒","600837":"海通证券","600845":"宝信软件",
    "600886":"国投电力","600887":"伊利股份","600893":"航发动力","600900":"长江电力",
    "600905":"三峡能源","600941":"中国移动","601006":"大秦铁路","601012":"隆基绿能",
    "601021":"春秋航空","601066":"中信建投","601088":"中国神华","601100":"恒立液压",
    "601111":"中国国航","601127":"赛力斯","601138":"工业富联","601166":"兴业银行",
    "601211":"国泰君安","601225":"陕西煤业","601238":"广汽集团","601288":"农业银行",
    "601318":"中国平安","601328":"交通银行","601336":"新华保险","601377":"兴业证券",
    "601390":"中国中铁","601398":"工商银行","601600":"中国铝业","601601":"中国太保",
    "601615":"明阳智能","601618":"中国中冶","601628":"中国人寿","601668":"中国建筑",
    "601689":"拓普集团","601728":"中国电信","601766":"中国中车","601800":"中国交建",
    "601816":"京沪高铁","601857":"中国石油","601888":"中国中免","601899":"紫金矿业",
    "601919":"中远海控","601939":"建设银行","601985":"中国核电","601988":"中国银行",
    "603259":"药明康德","603288":"海天味业","603501":"韦尔股份","603799":"华友钴业",
    "603993":"洛阳钼业","688005":"容百科技","688008":"澜起科技","688012":"中微公司",
    "688036":"传音控股","688041":"海光信息","688111":"金山办公","688126":"沪硅产业",
    "688169":"石头科技","688185":"康希诺","688187":"时代电气","688223":"晶科能源",
    "688256":"寒武纪","688271":"联影医疗","688347":"华虹公司","688390":"固德威",
    "688396":"华润微","688472":"阿特斯","688561":"奇安信","688599":"天合光能",
    "688608":"恒玄科技","688728":"格科微","688777":"中控技术","688819":"天能股份",
    "688981":"中芯国际","830832":"齐鲁华信","830879":"基康仪器","920802":"春光智能",
    "920809":"云星科技","920832":"齐鲁华信","920839":"万通液压",
}

def analyze_stock(code):
    price_path = f".cache/prices_{code}.csv"
    val_path = f".cache/valuation_{code}.csv"
    if not os.path.exists(price_path):
        return None
    try:
        df = pd.read_csv(price_path, index_col=0, parse_dates=True)
        if len(df) < 50:
            return None
        closes = df['close'].values
        volumes = df['volume'].values
        cur = closes[-1]

        # RSI
        rsi = 50.0
        if len(closes) >= 15:
            deltas = np.diff(closes[-15:])
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_g = np.mean(gains)
            avg_l = np.mean(losses)
            if avg_l > 0:
                rsi = 100 - 100/(1 + avg_g/avg_l)

        # MA
        ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else cur
        ma50 = np.mean(closes[-50:]) if len(closes) >= 50 else ma20
        ma200 = np.mean(closes[-200:]) if len(closes) >= 200 else ma50

        # MACD
        ema12 = pd.Series(closes).ewm(span=12).mean().values[-1]
        ema26 = pd.Series(closes).ewm(span=26).mean().values[-1]
        macd = ema12 - ema26

        # BB position
        bb_mid = ma20
        bb_std = np.std(closes[-20:])
        bb_pos = (cur - bb_mid + 2*bb_std) / (4*bb_std) if bb_std > 0 else 0.5

        # Valuation — 从估值CSV的管道分隔历史数据中计算分位
        pe_pct = pb_pct = 50.0
        if os.path.exists(val_path):
            vdf = pd.read_csv(val_path, index_col=0)
            # PE历史: 管道分隔的字符串 "21.25|21.25|...|13.3"
            if 'pe_history' in vdf.columns:
                ph = vdf['pe_history'].dropna()
                if len(ph) > 0:
                    pes = np.array([float(x) for x in str(ph.iloc[-1]).split('|') if x.strip()])
                    if len(pes) > 10 and pes[-1] > 0:
                        pe_pct = np.sum(pes < pes[-1]) / len(pes) * 100
            if 'pb_history' in vdf.columns:
                ph2 = vdf['pb_history'].dropna()
                if len(ph2) > 0:
                    pbs = np.array([float(x) for x in str(ph2.iloc[-1]).split('|') if x.strip()])
                    if len(pbs) > 10 and pbs[-1] > 0:
                        pb_pct = np.sum(pbs < pbs[-1]) / len(pbs) * 100

        # Trend
        if ma20 > ma50 * 1.01: trend = 'up'
        elif ma20 < ma50 * 0.99: trend = 'down'
        else: trend = 'sideways'

        # Chg 20d, 5d, 3d
        chg_20d = (cur - closes[-21]) / closes[-21] * 100 if len(closes) >= 21 else 0
        chg_5d = (cur - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
        chg_3d = (cur - closes[-4]) / closes[-4] * 100 if len(closes) >= 4 else 0

        # Momentum direction: 加速跌 / 减速跌 / 企稳 / 上涨
        # 3日 vs 5日: 3日跌幅更大 → 加速下跌
        momentum_accel = chg_3d - chg_5d  # 负数=加速下跌, 正数=跌速放缓
        falling_knife = trend == 'down' and chg_3d < -3 and momentum_accel < -1  # 加速下跌中

        # Score (重新设计: 找即将上涨的，不是找便宜的)
        score = 50

        # 估值 — 始终重要
        if pe_pct is not None:
            score += max(0, min(20, (1 - pe_pct/100) * 20))
        if pb_pct is not None:
            score += max(0, min(10, (1 - pb_pct/100) * 10))

        # RSI — 只在非下跌趋势或跌速放缓时加分
        if not np.isnan(rsi):
            if trend == 'up':
                if rsi < 25: score += 12
                elif rsi < 30: score += 8
                elif rsi < 35: score += 5
            elif trend == 'sideways':
                if rsi < 25: score += 8
                elif rsi < 30: score += 5
            else:  # trend down — RSI 超卖是常态，少加分
                if rsi < 25 and momentum_accel > -0.5: score += 5  # 极端+放缓才加分
                elif rsi < 30 and momentum_accel > 0: score += 3   # 减速跌才加分

        # 趋势
        if trend == 'up': score += 10
        elif trend == 'sideways': score += 4
        else: score -= 5  # 下跌趋势惩罚

        # MACD
        if macd > 0: score += 5

        # BB — 只在非加速下跌时加分
        if not np.isnan(bb_pos):
            if not falling_knife:
                if bb_pos < 0.1: score += 6
                elif bb_pos < 0.25: score += 3
            else:
                if bb_pos < 0.1: score += 2  # 加速跌时布林下轨减分力度

        # 超跌反弹潜力 — 只有跌速放缓(筑底)才加分
        if chg_20d < -15 and momentum_accel > -1:
            score += 5

        # 加速下跌惩罚
        if falling_knife:
            score -= 8

        # 短期动量方向
        if chg_3d > 1: score += 4          # 近3日在涨
        elif chg_3d < -3: score -= 4       # 近3日大跌

        score = max(0, min(100, score))

        # Signals
        signals = []
        if not np.isnan(rsi) and rsi < 30:
            if trend != 'down' or momentum_accel > 0:
                signals.append(f"RSI{rsi:.0f}超卖(筑底)")
            else:
                signals.append(f"RSI{rsi:.0f}超卖(注意飞刀)")
        if pe_pct is not None and pe_pct < 15: signals.append(f"PE{pe_pct:.0f}%极低")
        if pb_pct is not None and pb_pct < 15: signals.append(f"PB{pb_pct:.0f}%极低")
        if macd > 0: signals.append("MACD金叉")
        if trend == 'up': signals.append("趋势向上")
        if chg_20d < -15: signals.append(f"超跌{chg_20d:.0f}%")
        if falling_knife: signals.append("⚠️加速下跌")
        if momentum_accel > 0 and chg_3d < 0: signals.append("跌速放缓")
        if bb_pos < 0.15 and not falling_knife: signals.append("布林下轨超卖")

        return {
            'code': code, 'price': cur, 'score': score,
            'rsi': rsi, 'pe_pct': pe_pct, 'pb_pct': pb_pct,
            'trend': trend, 'chg_20d': chg_20d, 'chg_3d': chg_3d,
            'momentum_accel': momentum_accel,
            'falling_knife': falling_knife,
            'signals': '; '.join(signals) if signals else '无特殊信号',
        }
    except Exception as e:
        return None

# Main
results = []
for f in sorted(os.listdir('.cache')):
    if not f.startswith('prices_'):
        continue
    code = f.replace('prices_','').replace('.csv','')
    if code in ('159915','159919','510050','510300','512100'):
        continue
    r = analyze_stock(code)
    if r:
        results.append(r)

results.sort(key=lambda x: x['score'], reverse=True)

print(f'{"#":<3} {"代码":<8} {"名称":<8} {"现价":>8} {"评分":>4} {"RSI":>5} {"PE%":>5} {"PB%":>5} {"趋势":<4} {"3日":>6} {"20日":>6}  {"信号"}')
print(f'{"="*100}')
for i, r in enumerate(results[:20]):
    name = STOCK_NAMES.get(r['code'], '?')[:8]
    trend_icon = '↑' if r['trend']=='up' else ('↓' if r['trend']=='down' else '→')
    accel = r.get('momentum_accel', 0)
    accel_str = f'{accel:+.1f}%'
    knife = '⚠️' if r.get('falling_knife') else '  '
    chg3 = r['chg_3d']
    chg20 = r['chg_20d']
    sig = r['signals']
    print(f'{knife}{i+1:<3} {r["code"]:<8} {name:<8} {r["price"]:>8.2f} {r["score"]:>4.0f} {r["rsi"]:>5.0f} {r["pe_pct"]:>5.0f} {r["pb_pct"]:>5.0f} {trend_icon:<4} {chg3:>+5.0f}% {chg20:>+5.0f}%  {sig}')

print(f'\n{"="*75}')
hi = sum(1 for r in results if r['score']>=70)
mid = sum(1 for r in results if 55<=r['score']<70)
lo = sum(1 for r in results if r['score']<55)
print(f'共{len(results)}只 | 🔥≥70:{hi} | 🟡55-69:{mid} | ⚪<55:{lo}')
