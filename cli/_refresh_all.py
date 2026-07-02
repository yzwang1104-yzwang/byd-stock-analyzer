"""Batch refresh all stock caches — force real-time data."""
import sys,io,os,time
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace')
from core.data_fetcher import fetch_normalized_data

files=sorted([f for f in os.listdir('.cache') if f.startswith('prices_')])
total=len(files)
ok=0; fail=0
print(f'开始批量刷新 {total} 只股票...')
for i,f in enumerate(files):
    code=f.replace('prices_','').replace('.csv','')
    if code in ('159915','159919','510050','510300','512100'):
        continue
    try:
        d=fetch_normalized_data(code,force_refresh=True)
        if d and d.prices: ok+=1
        else: fail+=1
    except: fail+=1
    if (i+1)%200==0:
        print(f'  {i+1}/{total}  OK:{ok} FAIL:{fail}')
print(f'完成: {ok}成功 {fail}失败 / {total}总计')
