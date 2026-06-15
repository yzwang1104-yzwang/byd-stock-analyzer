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
class Position:
    stock_code: str
    entries: list[Entry] = field(default_factory=list)
    trigger_base: float | None = None  # 手动覆盖加仓基线

    @property
    def avg_cost(self) -> float:
        if not self.entries:
            return 0.0
        total_cost = sum(e.price * e.shares for e in self.entries)
        total_shares = sum(e.shares for e in self.entries)
        return total_cost / total_shares if total_shares > 0 else 0.0

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
        pnl_pct = (current_price / self.avg_cost - 1) * 100
        return {"pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2)}


# ====== 文件读写 ======

def load_position(stock_code: str) -> Optional[Position]:
    path = POSITION_FILE / f"{stock_code}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        entries = [Entry(**e) for e in data.get("entries", [])]
        return Position(stock_code=data["stock_code"], entries=entries, trigger_base=data.get("trigger_base"))
    except (json.JSONDecodeError, KeyError):
        return None


def save_position(pos: Position) -> None:
    POSITION_FILE.mkdir(parents=True, exist_ok=True)
    path = POSITION_FILE / f"{pos.stock_code}.json"
    data = {
        "stock_code": pos.stock_code,
        "trigger_base": pos.trigger_base,
        "entries": [{"date": e.date, "price": e.price, "shares": e.shares, "entry_type": e.entry_type} for e in pos.entries],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def add_entry(stock_code: str, price: float, shares: int, entry_date: Optional[str] = None) -> Position:
    pos = load_position(stock_code) or Position(stock_code=stock_code)
    if entry_date is None:
        entry_date = date.today().isoformat()
    etype = "initial" if not pos.entries else f"add_{pos.add_count + 1}"
    pos.entries.append(Entry(date=entry_date, price=price, shares=shares, entry_type=etype))
    save_position(pos)
    return pos


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
