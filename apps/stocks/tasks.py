"""Celery 异步任务——数据获取和模型运算。

红线 #17: 异步任务不阻塞请求。
开发环境 CELERY_TASK_ALWAYS_EAGER=True 时同步执行，不影响 CLI 使用。
"""

from celery import shared_task


@shared_task
def fetch_stock_data_async(stock_code: str) -> dict:
    """异步获取股票 K 线数据。"""
    from core.data_fetcher import fetch_normalized_data

    data = fetch_normalized_data(stock_code=stock_code, force_refresh=True)
    return {
        "stock_code": data.stock_code,
        "latest_price": data.latest_price,
        "trading_days": data.trading_days,
        "data_date": data.data_date.isoformat(),
    }


@shared_task
def run_analysis_async(code: str) -> dict:
    """异步运行完整分析流水线。"""
    from apps.stocks.services import run_analysis

    return run_analysis(code)


@shared_task
def refresh_all_caches_async(stock_codes: list[str]) -> dict:
    """异步批量刷新缓存（用于定时任务）。"""
    from core.data_fetcher import fetch_normalized_data

    ok, fail = 0, 0
    for code in stock_codes:
        if code in ("159915", "159919", "510050", "510300", "512100"):
            continue
        try:
            d = fetch_normalized_data(stock_code=code, force_refresh=True)
            if d and d.prices:
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
    return {"ok": ok, "fail": fail, "total": len(stock_codes)}
