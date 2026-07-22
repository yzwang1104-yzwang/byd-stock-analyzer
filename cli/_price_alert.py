"""价格提醒 — 比亚迪 002594 到达目标价位时告警。"""

import io
import ssl
import sys
import urllib.request
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 监控配置: 代码 → 提醒价位
# 补仓规则: -10%/#1, -20%/#2, -30%/#3，趋势DN不补
ALERTS = {
    # === 关注买入 ===
    "002594": [84, 80, 78],     # 比亚迪: 关注/买点/绝佳
    "600085": [24.00],           # 同仁堂: 回调买点
    "601727": [5.80],            # 上海电气: 超卖反弹点
    "688825": [8.66],            # 长鑫科技: 破发价(上市后)

    # === 持仓补仓提醒 ===
    "000983": [5.67, 5.04],      # 山西焦煤 avg6.30 #1-10% #2-20%
    "001382": [14.09, 12.52],    # 新亚电缆 avg15.65 #1-10% #2-20%
    "002855": [7.69, 6.66],      # 捷荣技术 avg9.51 #1✅8.56 #2#3
    "600438": [8.96, 7.84],      # 通威股份 avg11.21 #2#3(#1✅10.09已加)
    "600560": [9.52, 8.46],      # 金自天正 avg10.58 #1-10% #2-20%
    "603097": [13.93, 12.38],    # 江苏华辰 avg15.48 #1-10% #2-20%
    "603334": [29.17, 25.93],    # 丰倍生物 avg32.41 #1-10% #2-20%
}

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def check():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    triggered = []

    for code, targets in ALERTS.items():
        try:
            prefix = "nq" if code.startswith(("9", "8")) else ("sz" if code.startswith(("0", "3")) else "sh")
            url = f"https://qt.gtimg.cn/q={prefix}{code}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=3, context=_ssl_ctx).read()
            parts = raw.decode("gbk").split("~")
            cur = float(parts[3])
            name = parts[1]

            for t in targets:
                if cur <= t:
                    triggered.append(f"⚡ {code} {name} {cur:.2f} <= {t} 已达提醒价!")
        except Exception:
            pass

    if triggered:
        print(f"[{now}]")
        for t in triggered:
            print(f"  {t}")
        print()


if __name__ == "__main__":
    check()
