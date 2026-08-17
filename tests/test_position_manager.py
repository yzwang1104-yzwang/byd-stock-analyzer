"""position_manager.py 单元测试 — 编码契约与读写往返。

背景: save_position() 以 UTF-8 写入(ensure_ascii=False 含中文 note),
      load_position() 曾无编码参数读取, 在 GBK locale 的 Windows 上崩溃:
      UnicodeDecodeError: 'gbk' codec can't decode byte 0xb9
"""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.position_manager as pm


def _write_position_file(tmp_path: Path, code: str, content: dict, encoding: str = "utf-8") -> Path:
    """写入持仓 JSON 文件, 返回文件路径。"""
    pos_dir = tmp_path / ".position_history"
    pos_dir.mkdir(parents=True, exist_ok=True)
    path = pos_dir / f"{code}.json"
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding=encoding)
    return path


def test_load_position_utf8_chinese_note(monkeypatch, tmp_path):
    """UTF-8 含中文 note 的持仓文件必须可正常读取(2026-08-17 sell_alert 崩溃根因)。"""
    monkeypatch.setattr(pm, "POSITION_FILE", tmp_path / ".position_history")
    _write_position_file(
        tmp_path,
        "000096",
        {
            "stock_code": "000096",
            "trigger_base": None,
            "entries": [{"date": "2026-08-13", "price": 8.05, "shares": 100, "entry_type": "initial"}],
            "adjustments": [{"date": "2026-08-13", "amount": -5.0, "note": "过户费"}],
        },
    )

    pos = pm.load_position("000096")

    assert pos is not None
    assert pos.avg_cost == pytest.approx(8.10)  # 8.05 + 5.0/100 费用摊薄
    assert pos.adjustments[0].note == "过户费"


def test_save_then_load_roundtrip_chinese(monkeypatch, tmp_path):
    """save_position → load_position 中文 note 往返一致。"""
    monkeypatch.setattr(pm, "POSITION_FILE", tmp_path / ".position_history")

    pos = pm.Position(stock_code="600161")
    pos.entries.append(pm.Entry(date="2026-08-13", price=12.55, shares=100))
    pos.adjustments.append(pm.Adjustment(date="2026-08-13", amount=-5.0, note="印花税+过户费"))
    pm.save_position(pos)

    loaded = pm.load_position("600161")

    assert loaded is not None
    assert loaded.adjustments[0].note == "印花税+过户费"
    assert loaded.avg_cost == pos.avg_cost


def test_load_position_missing_file(monkeypatch, tmp_path):
    """不存在的持仓文件返回 None, 不抛异常。"""
    monkeypatch.setattr(pm, "POSITION_FILE", tmp_path / ".position_history")
    assert pm.load_position("999999") is None


def test_load_position_broken_json(monkeypatch, tmp_path):
    """损坏的 JSON 返回 None, 不抛异常。"""
    monkeypatch.setattr(pm, "POSITION_FILE", tmp_path / ".position_history")
    _write_position_file(tmp_path, "000001", {"stock_code": "000001"})
    path = tmp_path / ".position_history" / "000001.json"
    path.write_text("{broken json", encoding="utf-8")

    assert pm.load_position("000001") is None


def test_close_position_writes_utf8(monkeypatch, tmp_path):
    """close_position 归档文件必须与读取端同一编码契约(UTF-8)。"""
    monkeypatch.setattr(pm, "POSITION_FILE", tmp_path / ".position_history")
    monkeypatch.setattr(pm, "CLOSED_DIR", tmp_path / ".closed_positions")
    _write_position_file(
        tmp_path,
        "600795",
        {
            "stock_code": "600795",
            "trigger_base": None,
            "entries": [{"date": "2026-06-24", "price": 4.71, "shares": 100, "entry_type": "initial"}],
            "adjustments": [
                {"date": "2026-07-15", "amount": 14.10, "note": "股息入账"},
                {"date": "2026-08-03", "amount": -5.0, "note": "印花税+过户费"},
            ],
        },
    )

    summary = pm.close_position("600795", sell_price=5.10)

    # 归档文件名带当天日期，不能硬编码（跨零点运行会失败）
    today = date.today().strftime("%Y-%m-%d")
    closed_path = tmp_path / ".closed_positions" / f"600795_{today}.json"
    raw = closed_path.read_bytes()
    # UTF-8 必须能解码(写端曾无编码参数, 在 GBK locale 下会写成 GBK)
    decoded = raw.decode("utf-8")
    assert "印花税" in decoded
    assert summary["net_profit"] > 0
    # 活跃持仓文件已删除
    assert not (tmp_path / ".position_history" / "600795.json").exists()
