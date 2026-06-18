"""TDD: trading_calendar.py — 交易日历测试"""
from datetime import date
from core.trading_calendar import is_trading_day, next_trading_day


class TestIsTradingDay:
    """is_trading_day() — 判断是否为A股交易日"""

    def test_weekday_is_trading_day(self):
        """周一至周五（非法定假日）应为交易日"""
        # 2026-06-15 是周一，非假日
        ok, reason = is_trading_day(date(2026, 6, 15))
        assert ok is True
        assert reason == "正常交易日"

    def test_saturday_is_not_trading_day(self):
        """周六应为休市"""
        ok, reason = is_trading_day(date(2026, 6, 20))
        assert ok is False
        assert reason == "周末"

    def test_sunday_is_not_trading_day(self):
        """周日应为休市"""
        ok, reason = is_trading_day(date(2026, 6, 21))
        assert ok is False
        assert reason == "周末"

    def test_dragon_boat_festival_holiday(self):
        """端午节假期（6/19周五）应为休市"""
        ok, reason = is_trading_day(date(2026, 6, 19))
        assert ok is False
        assert reason == "端午节"

    def test_spring_festival_holiday(self):
        """春节假期应为休市"""
        ok, reason = is_trading_day(date(2026, 2, 17))
        assert ok is False
        assert reason == "春节"

    def test_makeup_workday_is_trading(self):
        """调休工作日应为交易日（春节前补班）"""
        ok, reason = is_trading_day(date(2026, 2, 14))
        assert ok is True
        assert "调休" in reason

    def test_national_day_holiday(self):
        """国庆假期应为休市"""
        ok, reason = is_trading_day(date(2026, 10, 1))
        assert ok is False
        assert reason == "国庆节"

    def test_default_today_does_not_throw(self):
        """无参数调用不抛异常"""
        ok, reason = is_trading_day()
        assert isinstance(ok, bool)
        assert isinstance(reason, str)


class TestNextTradingDay:
    def test_next_after_friday_is_monday(self):
        """周五之后的下一个交易日应为下周一"""
        nxt = next_trading_day(date(2026, 6, 19))  # 周五端午节
        assert nxt == date(2026, 6, 22)  # 下周一

    def test_next_after_weekday(self):
        """普通周一之后应为周二"""
        nxt = next_trading_day(date(2026, 6, 15))  # 周一
        assert nxt == date(2026, 6, 16)  # 周二
