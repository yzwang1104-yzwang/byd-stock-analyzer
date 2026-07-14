"""价格提醒 — 比亚迪 002594 到达目标价位时告警。"""

import io
import ssl
import sys
import urllib.request
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 监控配置: 代码 → 提醒价位
ALERTS = {
    "002594": [84, 80, 78],  # 比亚迪: 84(关注), 80(买点), 78(绝佳)
    "600438": [10.75],        # 通威: 加仓触发价
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
