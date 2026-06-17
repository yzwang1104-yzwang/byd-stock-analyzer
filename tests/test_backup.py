"""TDD: 备份守护脚本 — 备份、恢复、清理。"""
import os
import shutil
from pathlib import Path
from datetime import date, timedelta
from unittest import mock


class TestBackupCore:
    """备份核心逻辑测试。"""

    def test_backup_copies_files(self, tmp_path, monkeypatch):
        """备份应该将文件复制到日期目录。"""
        from cli.backup import backup, _auto_push, _cleanup_old

        # 禁止 auto_push 和 cleanup
        monkeypatch.setattr("cli.backup._auto_push", lambda: None)
        monkeypatch.setattr("cli.backup._cleanup_old", lambda today: None)

        # 临时项目目录
        proj = tmp_path / "project"
        proj.mkdir()
        src_file = proj / "CLAUDE.md"
        src_file.write_text("test content", encoding="utf-8")

        # 临时备份目录
        backup_root = tmp_path / ".claude" / "backups"
        monkeypatch.setattr("cli.backup.BACKUP_ROOT", backup_root)

        # 临时 BACKUP_ITEMS
        monkeypatch.setattr("cli.backup.BACKUP_ITEMS", [
            (src_file, False),
        ])

        result = backup(date(2026, 6, 17))

        snapshot = backup_root / "2026-06-17"
        assert snapshot.exists()
        backed = snapshot / "CLAUDE.md"
        assert backed.exists()
        assert backed.read_text() == "test content"

    def test_backup_handles_missing_source(self, tmp_path, monkeypatch):
        """不存在的源文件不崩溃。"""
        from cli.backup import backup

        monkeypatch.setattr("cli.backup._auto_push", lambda: None)
        monkeypatch.setattr("cli.backup._cleanup_old", lambda today: None)

        backup_root = tmp_path / ".claude" / "backups"
        monkeypatch.setattr("cli.backup.BACKUP_ROOT", backup_root)

        nonexistent = tmp_path / "does_not_exist.txt"
        monkeypatch.setattr("cli.backup.BACKUP_ITEMS", [
            (nonexistent, False),
        ])

        result = backup(date(2026, 6, 17))
        assert result is not None  # 不崩溃


class TestRestore:
    """恢复功能测试。"""

    def test_restore_from_latest(self, tmp_path, monkeypatch):
        """从最新备份恢复文件内容。"""
        from cli.backup import restore

        backup_root = tmp_path / ".claude" / "backups"
        monkeypatch.setattr("cli.backup.BACKUP_ROOT", backup_root)

        # 目标文件在 tmp_path 下
        src = tmp_path / "RESTORE_TEST.md"
        src.write_text("before")

        # 创建备份（和源文件同名）
        snap = backup_root / "2026-06-17"
        snap.mkdir(parents=True)
        (snap / "RESTORE_TEST.md").write_text("after backup")

        # BACKUP_ITEMS 用文件名，restore 用 Path(name) 恢复到 CWD
        # monkeypatch Path 让恢复写到 tmp_path
        monkeypatch.setattr("cli.backup.BACKUP_ITEMS", [(src, False)])

        import cli.backup as bk
        _orig_path = bk.Path
        def _patched_path(p):
            if p == "RESTORE_TEST.md":
                return _orig_path(src)
            return _orig_path(p)
        monkeypatch.setattr("cli.backup.Path", _patched_path)

        ok = restore()
        assert ok is True
        assert src.read_text() == "after backup"

    def test_restore_no_backups(self, tmp_path, monkeypatch):
        """无备份时返回 False。"""
        from cli.backup import restore

        empty = tmp_path / "empty_dir"
        monkeypatch.setattr("cli.backup.BACKUP_ROOT", empty)

        ok = restore()
        assert ok is False


class TestCleanup:
    """清理功能测试。"""

    def test_old_backups_removed(self, tmp_path, monkeypatch):
        """7天前的备份应被删除。"""
        from cli.backup import _cleanup_old

        root = tmp_path / "backups"
        monkeypatch.setattr("cli.backup.BACKUP_ROOT", root)

        old = root / "2026-06-01"
        old.mkdir(parents=True)
        (old / "x.txt").write_text("old")

        new = root / "2026-06-17"
        new.mkdir(parents=True)
        (new / "x.txt").write_text("new")

        _cleanup_old(date(2026, 6, 17))

        assert not old.exists()
        assert new.exists()
