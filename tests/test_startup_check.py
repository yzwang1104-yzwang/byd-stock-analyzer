"""TDD: 会话启动检查脚本 — 4项检查各场景。"""
import os
from pathlib import Path
from datetime import datetime, timedelta
from unittest import mock


class TestGitStatus:
    """Git 状态检查。"""

    def test_clean_workspace(self, monkeypatch):
        """干净工作区返回 ok=True。"""
        from cli.startup_check import check_git_status

        def mock_run(*args, **kwargs):
            r = mock.MagicMock()
            r.stdout = ""
            return r

        monkeypatch.setattr("subprocess.run", mock_run)
        result = check_git_status()
        assert result["ok"] is True
        assert result["dirty_files"] == 0

    def test_dirty_workspace(self, monkeypatch):
        """有未提交文件时返回 ok=False。"""
        from cli.startup_check import check_git_status

        def mock_run(*args, **kwargs):
            r = mock.MagicMock()
            r.stdout = "M  CLAUDE.md\n?? new_file.py\n"
            return r

        monkeypatch.setattr("subprocess.run", mock_run)
        result = check_git_status()
        assert result["ok"] is False
        assert result["dirty_files"] == 2

    def test_git_error_handled(self, monkeypatch):
        """git 命令失败时不崩溃。"""
        from cli.startup_check import check_git_status

        def mock_run(*args, **kwargs):
            raise FileNotFoundError("git not found")

        monkeypatch.setattr("subprocess.run", mock_run)
        result = check_git_status()
        assert result["ok"] is False
        assert "error" in result


class TestClaudeMd:
    """CLAUDE.md 检查。"""

    def test_fresh_claude_md(self, tmp_path, monkeypatch):
        """最近更新的 CLAUDE.md 通过检查。"""
        from cli.startup_check import check_claude_md

        md = tmp_path / "CLAUDE.md"
        md.write_text("# test")
        monkeypatch.setattr("cli.startup_check.Path", lambda p: md if p == "CLAUDE.md" else Path(p))

        result = check_claude_md()
        assert result["ok"] is True
        assert result["days_ago"] <= 0  # 刚创建的文件

    def test_missing_claude_md(self, monkeypatch):
        """不存在的 CLAUDE.md 返回 False。"""
        from cli.startup_check import check_claude_md

        # 指向不存在的文件
        monkeypatch.setattr("cli.startup_check.Path", lambda p: Path("/nonexistent/CLAUDE.md"))

        result = check_claude_md()
        assert result["ok"] is False

    def test_stale_claude_md(self, tmp_path, monkeypatch):
        """3天前的 CLAUDE.md 返回 ok=False。"""
        from cli.startup_check import check_claude_md

        md = tmp_path / "CLAUDE.md"
        md.write_text("# old")
        # 修改 mtime 到 3 天前
        old_time = (datetime.now() - timedelta(days=3)).timestamp()
        os.utime(str(md), (old_time, old_time))

        monkeypatch.setattr("cli.startup_check.Path", lambda p: md if p == "CLAUDE.md" else Path(p))

        result = check_claude_md()
        assert result["ok"] is False
        assert result["days_ago"] >= 3


class TestPositions:
    """持仓文件检查。"""

    def test_positions_exist(self, tmp_path, monkeypatch):
        """持仓文件存在时通过检查。"""
        from cli.startup_check import check_positions

        pos_dir = tmp_path / ".position_history"
        pos_dir.mkdir()
        (pos_dir / "600370.json").write_text("{}")

        monkeypatch.setattr("cli.startup_check.Path", lambda p: pos_dir if p == ".position_history" else Path(p))

        result = check_positions()
        assert result["ok"] is True
        assert result["files"] == 1

    def test_no_positions_dir(self, monkeypatch):
        """无持仓目录时返回 ok=True（可能无持仓）。"""
        from cli.startup_check import check_positions

        monkeypatch.setattr("cli.startup_check.Path", lambda p: Path("/nonexistent/pos"))

        result = check_positions()
        assert result["ok"] is True
        assert result["files"] == 0


class TestPredictionHistory:
    """预测历史检查。"""

    def test_prediction_files_exist(self, tmp_path, monkeypatch):
        """预测文件存在时通过检查。"""
        from cli.startup_check import check_prediction_history

        pred_dir = tmp_path / ".prediction_history"
        pred_dir.mkdir()
        (pred_dir / "predictions_002594.json").write_text(
            '[{"id":1,"current_price":90},{"id":2,"current_price":91}]'
        )

        monkeypatch.setattr("cli.startup_check.Path", lambda p: pred_dir if p == ".prediction_history" else Path(p))

        result = check_prediction_history()
        assert result["ok"] is True
        assert result["files"] == 1
        assert result["total_records"] == 2

    def test_no_prediction_dir(self, monkeypatch):
        """无预测目录时返回 ok=False。"""
        from cli.startup_check import check_prediction_history

        monkeypatch.setattr("cli.startup_check.Path", lambda p: Path("/nonexistent/pred"))

        result = check_prediction_history()
        assert result["ok"] is False
