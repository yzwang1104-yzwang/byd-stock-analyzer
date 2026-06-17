"""TDD: 预测追踪模块 — 方向准确率不应被自动回填污染。"""
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest


# ── Mock data ────────────────────────────────────────────────

def _make_records(predictions: list[dict]) -> list[dict]:
    """构建预测记录列表。"""
    records = []
    for i, p in enumerate(predictions):
        records.append({
            "id": i + 1,
            "timestamp": f"2026-06-17T{i:02d}:00:00",
            "stock_code": "002594",
            "current_price": p.get("current_price", 90.0),
            "predicted_low": p.get("predicted_low", 89.0),
            "predicted_high": p.get("predicted_high", 91.0),
            "predicted_close": p.get("predicted_close", 90.5),
            "actual_close": p.get("actual_close"),
            "error": p.get("error"),
            "backfill_type": p.get("backfill_type", ""),
        })
    return records


# ── Tests ────────────────────────────────────────────────────

class TestDirectionAccuracyNotContaminated:
    """方向准确率应排除 auto-backfill，仅用真实收盘价回填的数据。"""

    def test_auto_backfill_excluded_from_direction(self, monkeypatch):
        """RED: auto-backfill 的记录应该被排除出方向准确率计算。"""
        from core.prediction_tracker import compute_accuracy

        records = _make_records([
            # 3条真实手动回填 — 预测up，实际也up → 应该全对
            {"current_price": 90, "predicted_close": 91, "actual_close": 91.5, "error": 0.5, "backfill_type": "manual"},
            {"current_price": 91.5, "predicted_close": 92, "actual_close": 92.3, "error": 0.3, "backfill_type": "manual"},
            {"current_price": 92.3, "predicted_close": 93, "actual_close": 93.1, "error": 0.1, "backfill_type": "manual"},
            # 10条auto-backfill — 用盘中价代替收盘价，全是错的（预测up但"实际"down）
            *[{"current_price": 95, "predicted_close": 96, "actual_close": 94, "error": -2, "backfill_type": "auto"} for _ in range(10)],
        ])

        # Mock _load_records to return our test data
        with mock.patch("core.prediction_tracker._load_records", return_value=records):
            result = compute_accuracy("002594")

        # 手动回填的方向准确率应该100% (3/3全对)
        assert result["manual_direction_accuracy"] == 100.0, \
            f"手动方向准确率应为100%，实际 {result['manual_direction_accuracy']}%"

        # 总方向准确率应该主要反映手动数据，而非被auto污染到极低
        # 如果auto被混入：3正确 / (3+10)总数 = 23%
        # 正确做法：总方向准确率也排除auto
        assert result["direction_accuracy"] > 50, \
            f"方向准确率({result['direction_accuracy']}%)被auto-backfill污染，" \
            f"应该排除auto记录"


    def test_no_manual_data_reports_insufficient(self, monkeypatch):
        """没有手动回填数据时，方向准确率应标注数据不足。"""
        from core.prediction_tracker import compute_accuracy

        records = _make_records([
            {"current_price": 90, "predicted_close": 91, "actual_close": 89, "error": -2, "backfill_type": "auto"},
            {"current_price": 89, "predicted_close": 90, "actual_close": 88, "error": -2, "backfill_type": "auto"},
            {"current_price": 88, "predicted_close": 89, "actual_close": 87, "error": -2, "backfill_type": "auto"},
            {"current_price": 87, "predicted_close": 88, "actual_close": 86, "error": -2, "backfill_type": "auto"},
            {"current_price": 86, "predicted_close": 87, "actual_close": 85, "error": -2, "backfill_type": "auto"},
        ])

        with mock.patch("core.prediction_tracker._load_records", return_value=records):
            result = compute_accuracy("002594")

        # 全是auto-backfill时，手动准确率应标注为无数据
        assert result["manual_direction_total"] == 0, \
            "没有手动回填时 manual_direction_total 应为0"


class TestBackfillTypePreserved:
    """backfill_type 字段必须正确保留和传递。"""

    def test_auto_backfill_marked_correctly(self):
        """auto回填的 backfill_type 必须是 'auto'。"""
        from core.prediction_tracker import backfill_actual

        records = _make_records([
            {"current_price": 90, "predicted_close": 91},
            {"current_price": 90, "predicted_close": 89},
            {"current_price": 90, "predicted_close": 90.5},
        ])

        with mock.patch("core.prediction_tracker._load_records", return_value=records):
            with mock.patch("core.prediction_tracker._save_records") as mock_save:
                n = backfill_actual("002594", 91.0, fill_type="auto")

        assert n == 3, "应回填3条"
        # 验证保存的记录
        saved_records = mock_save.call_args[0][1]
        for r in saved_records:
            assert r["backfill_type"] == "auto", \
                f"auto回填的 backfill_type 应为 'auto'，实际 {r.get('backfill_type')}"
