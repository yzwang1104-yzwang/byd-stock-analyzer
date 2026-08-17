"""sell_analysis.py 单元测试 — 已平仓持仓过滤（ZeroDivisionError 回归）。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _write_position(tmp_path: Path, code: str, entries: list[dict]) -> None:
    """写入一个持仓 JSON 文件（UTF-8）。"""
    pos_dir = tmp_path / ".position_history"
    pos_dir.mkdir(exist_ok=True)
    data = {"entries": entries, "adjustments": []}
    (pos_dir / f"{code}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def test_load_portfolio_skips_closed_position(tmp_path, monkeypatch):
    """已平仓持仓（total_shares=0）不应出现在卖出分析中 — 回归测试。

    背景：603097 卖出全部持仓后 entries 抵消为 0 股，avg_price=0，
    导致 main() 中 pnl_pct 除零崩溃（2026-08-17 事故）。
    """
    from cli import sell_analysis

    monkeypatch.setattr(sell_analysis, "POSITION_DIR", str(tmp_path / ".position_history"))

    # 已平仓：+100 买入，-100 卖出 → total_shares=0
    _write_position(tmp_path, "603097", [
        {"date": "2026-08-01", "price": 20.00, "shares": 100, "entry_type": "initial"},
        {"date": "2026-08-12", "price": 21.50, "shares": -100, "entry_type": "sell"},
    ])
    # 活跃持仓：+200 股，均价 5.00
    _write_position(tmp_path, "600795", [
        {"date": "2026-08-01", "price": 5.00, "shares": 200, "entry_type": "initial"},
    ])

    portfolio = sell_analysis._load_portfolio()
    codes = [code for code, _, _, _ in portfolio]

    assert codes == ["600795"], "已平仓持仓不应出现在卖出分析中"
    assert portfolio[0][2] > 0, "活跃持仓股数应为正"
    assert portfolio[0][3] > 0, "活跃持仓均价应大于 0"
