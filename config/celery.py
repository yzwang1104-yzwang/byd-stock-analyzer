"""Celery 应用配置——异步任务队列。

红线 #17: 数据获取、模型训练、邮件发送必须走 Celery，不阻塞请求。

开发环境默认同步执行（CELERY_TASK_ALWAYS_EAGER=True），生产需 Redis + worker。

usage:
    celery -A config worker -l info       # 启动 worker
    celery -A config beat -l info         # 启动定时任务
"""

import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("byd_stock_analyzer")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["apps.stocks"])
