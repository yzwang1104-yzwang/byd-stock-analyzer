"""持仓管理——买入记录、加仓判断、成本追踪。"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

POSITION_FILE = Path(".position_history")


@dataclass
class Entry:
    date: str  # ISO date
    price: float
    shares: int
    entry_type: str = "initial"  # "initial" | "add_1" | "add_2" | "add_3"


@dataclass
class Adjustment:
    """股息/费用调整记录。"""
    date: str
    amount: float   # 正=股息收入，负=费用支出
    note: str = ""  # "股息入账" / "交易佣金" / "印花税" 等


@dataclass
class Position:
    stock_code: str
    entries: list[Entry] = field(default_factory=list)
    adjustments: list[Adjustment] = field(default_factory=list)
    trigger_base: float | None = None  # 手动覆盖加仓基线

    @property
    def avg_cost(self) -> float:
        """考虑股息和费用后的真实成本均价。"""
        if not self.entries:
            return 0.0
        total_cost = sum(e.price * e.shares for e in self.entries)
        total_shares = sum(e.shares for e in self.entries)
        if total_shares == 0:
            return 0.0
        # 费用增加成本，股息降低成本
        net_cost = total_cost - self._net_adjustments
        return net_cost / total_shares

    @property
    def _net_adjustments(self) -> float:
        """净调整额 = 股息收入 - 费用支出。"""
        return sum(a.amount for a in self.adjustments)

    @property
    def total_shares(self) -> int:
        return sum(e.shares for e in self.entries)

    @property
    def total_cost(self) -> float:
        return self.avg_cost * self.total_shares

    @property
    def add_count(self) -> int:
        return sum(1 for e in self.entries if e.entry_type.startswith("add_"))

    @property
    def adds_remaining(self) -> int:
        return max(0, 3 - self.add_count)

    @property
    def last_price(self) -> float:
        return self.entries[-1].price if self.entries else 0.0

    @property
    def next_add_price(self) -> float:
        """下次加仓触发价 = 基线 × 90%"""
        base = self.trigger_base if self.trigger_base else self.last_price
        return round(base * 0.9, 2)

    @property
    def can_add(self) -> bool:
        return self.adds_remaining > 0

    def estimated_avg_after_add(self, add_price: float, add_shares: int) -> float:
        total_cost = self.total_cost + add_price * add_shares
        total_shares = self.total_shares + add_shares
        return total_cost / total_shares if total_shares > 0 else add_price

    def unrealized_pnl(self, current_price: float) -> dict:
        if not self.entries:
            return {"pnl": 0.0, "pnl_pct": 0.0}
        pnl = (current_price - self.avg_cost) * self.total_shares
        pnl_pct = (current_price / self.avg_cost - 1) * 100 if self.avg_cost else 0
        return {"pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2)}


# ====== 文件读写 ======

def load_position(stock_code: str) -> Optional[Position]:
    path = POSITION_FILE / f"{stock_code}.json"
    if not path.exists():
        return None
    try:
        # 写端 save_position() 固定 UTF-8, 读端必须一致, 否则 GBK locale 崩溃
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = [Entry(**e) for e in data.get("entries", [])]
        adjustments = [Adjustment(**a) for a in data.get("adjustments", [])]
        return Position(
            stock_code=data["stock_code"],
            entries=entries,
            adjustments=adjustments,
            trigger_base=data.get("trigger_base"),
        )
    except (json.JSONDecodeError, KeyError):
        return None


def save_position(pos: Position) -> None:
    POSITION_FILE.mkdir(parents=True, exist_ok=True)
    path = POSITION_FILE / f"{pos.stock_code}.json"
    data = {
        "stock_code": pos.stock_code,
        "trigger_base": pos.trigger_base,
        "entries": [
            {"date": e.date, "price": e.price, "shares": e.shares, "entry_type": e.entry_type}
            for e in pos.entries
        ],
        "adjustments": [
            {"date": a.date, "amount": a.amount, "note": a.note}
            for a in pos.adjustments
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_entry(stock_code: str, price: float, shares: int, entry_date: Optional[str] = None) -> Position:
    if price <= 0:
        raise ValueError(f"成交价必须为正数，收到: {price}")
    if shares <= 0:
        raise ValueError(f"股数必须为正数，收到: {shares}")
    pos = load_position(stock_code) or Position(stock_code=stock_code)
    if entry_date is None:
        entry_date = date.today().isoformat()
    etype = "initial" if not pos.entries else f"add_{pos.add_count + 1}"
    pos.entries.append(Entry(date=entry_date, price=price, shares=shares, entry_type=etype))
    save_position(pos)
    return pos


def add_dividend(stock_code: str, amount: float, note: str = "股息入账") -> Position:
    """记录股息收入（降低平均成本）。"""
    pos = load_position(stock_code)
    if not pos:
        raise ValueError(f"未找到持仓: {stock_code}")
    pos.adjustments.append(Adjustment(date=date.today().isoformat(), amount=amount, note=note))
    save_position(pos)
    return pos


def add_fee(stock_code: str, amount: float, note: str = "交易费用") -> Position:
    """记录交易费用（增加平均成本）。amount 为正值。"""
    pos = load_position(stock_code)
    if not pos:
        raise ValueError(f"未找到持仓: {stock_code}")
    pos.adjustments.append(Adjustment(date=date.today().isoformat(), amount=-abs(amount), note=note))
    save_position(pos)
    return pos


# ====== 卖出平仓 ======

CLOSED_DIR = Path(".closed_positions")


def close_position(stock_code: str, sell_price: float, sell_date: Optional[str] = None) -> dict:
    """平仓卖出，归档持仓文件，返回盈亏汇总。"""
    pos = load_position(stock_code)
    if not pos:
        raise ValueError(f"未找到持仓: {stock_code}")
    if sell_date is None:
        sell_date = date.today().isoformat()

    # 计算盈亏
    avg_cost = pos.avg_cost
    total_shares = pos.total_shares
    total_cost = avg_cost * total_shares
    total_revenue = sell_price * total_shares
    gross_profit = total_revenue - total_cost
    gross_pct = (sell_price / avg_cost - 1) * 100 if avg_cost > 0 else 0

    # 扣除费用估计（佣金0.03%+印花税0.1%+过户费0.002%，双向）
    fee_estimate = total_revenue * 0.00132  # ~0.132%
    net_profit = gross_profit - fee_estimate

    summary = {
        "stock_code": stock_code,
        "sell_date": sell_date,
        "sell_price": sell_price,
        "avg_cost": round(avg_cost, 4),
        "total_shares": total_shares,
        "holding_days": _calc_holding_days(pos.entries[0].date, sell_date),
        "total_cost": round(total_cost, 2),
        "total_revenue": round(total_revenue, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_pct": round(gross_pct, 2),
        "fee_estimate": round(fee_estimate, 2),
        "net_profit": round(net_profit, 2),
        "entries": [{"date": e.date, "price": e.price, "shares": e.shares} for e in pos.entries],
        "adjustments": [{"date": a.date, "amount": a.amount, "note": a.note} for a in pos.adjustments],
    }

    # 归档到 closed_positions
    CLOSED_DIR.mkdir(parents=True, exist_ok=True)
    closed_path = CLOSED_DIR / f"{stock_code}_{sell_date}.json"
    closed_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # 删除活跃持仓文件
    pos_path = POSITION_FILE / f"{stock_code}.json"
    if pos_path.exists():
        pos_path.unlink()

    return summary


def _calc_holding_days(buy_date: str, sell_date: str) -> int:
    """计算持仓天数。"""
    try:
        d1 = date.fromisoformat(buy_date)
        d2 = date.fromisoformat(sell_date)
        return (d2 - d1).days
    except (ValueError, TypeError):
        return 0


# ====== 加仓判断 ======

def should_add(pos: Position, current_price: float, score: int, trend: str) -> dict:
    """判断是否应该加仓。"""

    reasons = []
    warnings = []

    # 1. 价格条件
    if current_price <= pos.next_add_price:
        reasons.append(f"当前价 {current_price:.2f} ≤ 触发价 {pos.next_add_price:.2f}")
    else:
        gap_pct = (current_price / pos.next_add_price - 1) * 100
        reasons.append(f"当前价 {current_price:.2f} > 触发价 {pos.next_add_price:.2f}（还需跌 {gap_pct:.1f}%）")

    # 2. 次数限制
    if pos.can_add:
        reasons.append(f"剩余加仓次数: {pos.adds_remaining}")
    else:
        warnings.append("加仓次数已用尽（最多3次）")

    # 3. 基本面
    if score >= 30:
        reasons.append(f"评分 {score}/100 ≥ 30（基本面可接受）")
    else:
        warnings.append(f"评分 {score}/100 < 30（基本面恶化，阻止加仓）")

    # 4. 趋势
    if trend == "down":
        warnings.append("趋势向下——加仓需谨慎")
    elif trend in ("sideways_down",):
        warnings.append("趋势偏弱")

    # 5. 盈利状态
    pnl = pos.unrealized_pnl(current_price)
    if pnl["pnl_pct"] > 20:
        warnings.append(f"持仓已盈利 {pnl['pnl_pct']:.0f}%，建议减仓而非加仓")

    should = all([
        current_price <= pos.next_add_price,
        pos.can_add,
        score >= 30,
        pnl["pnl_pct"] <= 20,
    ])

    return {
        "should_add": should,
        "reasons": reasons,
        "warnings": warnings,
        "next_add_price": pos.next_add_price,
        "add_count": pos.add_count,
        "adds_remaining": pos.adds_remaining,
    }
