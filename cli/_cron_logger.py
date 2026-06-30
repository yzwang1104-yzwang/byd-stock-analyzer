"""Cron 任务日志 — 所有定时任务结果写入统一日志文件"""
import sys, io, os
from datetime import datetime
from pathlib import Path

LOG_FILE = Path(".prediction_history/cron_daily.log")


def log(task_name: str, result: str) -> None:
    """记录任务执行结果。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{now}] {task_name}\n{result}\n\n")


def read_today() -> str:
    """读取今日所有任务日志。"""
    if not LOG_FILE.exists():
        return "暂无日志"
    return LOG_FILE.read_text(encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python cli/_cron_logger.py <任务名> <结果>")
        sys.exit(1)
    log(sys.argv[1], sys.argv[2])
    print(f"已记录: {sys.argv[1]}")
