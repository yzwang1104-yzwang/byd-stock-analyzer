"""项目配置——所有可调参数集中管理。

设计原则:
- 运行时可通过环境变量覆盖
- 权重之和必须为 1.0
- 所有阈值为闭区间 [min, max]
"""

from dataclasses import dataclass, field


# ====== 股票标识 ======
STOCK_CODE = "002594"  # 比亚迪 A 股
STOCK_NAME = "比亚迪"
HK_STOCK_CODE = "1211.HK"  # 港股（Phase 2）

# ====== 评分因子权重（总计 1.0） ======
DEFAULT_WEIGHTS = {
    "valuation": 0.35,   # 估值因子
    "technical": 0.30,   # 技术因子
    "trend": 0.20,       # 趋势因子
    "volume": 0.10,      # 量能因子
    "sentiment": 0.05,   # 情绪因子
}

# ====== 技术指标参数 ======
MA_PERIODS = [20, 50, 200]
MACD_PARAMS = {"fast": 12, "slow": 26, "signal": 9}
RSI_PERIOD = 14
BOLLINGER_PARAMS = {"period": 20, "std_dev": 2}
ATR_PERIOD = 14
VOLUME_SMA_PERIOD = 20

# ====== 评分阈值 ======
@dataclass
class ScoreThresholds:
    strong_sell_max: int = 30  # 0-30: 强烈卖出
    sell_max: int = 55         # 31-55: 观望等待
    hold_max: int = 75         # 56-75: 可考虑买入
    buy_max: int = 90          # 76-90: 建议买入
    # 91-100: 强烈买入


SCORE_THRESHOLDS = ScoreThresholds()

# ====== 仓位建议 ======
POSITION_TIERS = [0, 25, 50, 75, 100]  # 百分比档位

# ====== 信号冷却 ======
SIGNAL_COOLDOWN_DAYS = 3  # 两次买入信号间隔 ≥ N 个交易日

# ====== 卖出触发 ======
SELL_RSI_THRESHOLD = 70        # RSI 超买阈值
SELL_PE_PERCENTILE = 80        # PE 分位阈值

# ====== 数据缓存 ======
CACHE_DIR = ".cache"
CACHE_MAX_AGE_HOURS = 6  # 缓存过期时间

# ====== RSI 超买/超卖 ======
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70


@dataclass
class ScoringConfig:
    """可序列化的评分配置。"""

    weights: dict[str, float] = field(default_factory=lambda: DEFAULT_WEIGHTS.copy())
    thresholds: ScoreThresholds = field(default_factory=ScoreThresholds)
    cooldown_days: int = SIGNAL_COOLDOWN_DAYS
    rsi_oversold: int = RSI_OVERSOLD
    rsi_overbought: int = RSI_OVERBOUGHT

    def validate(self) -> list[str]:
        """验证配置合法性。"""
        errors = []
        total = sum(self.weights.values())
        if abs(total - 1.0) > 0.01:
            errors.append(f"权重之和应为 1.0，当前为 {total}")
        if self.cooldown_days < 0:
            errors.append("冷却天数不能为负")
        return errors
