"""使用中ロック（sync/presence.py）と起動時ユーザー選択ダイアログのテスト。"""
import json
from datetime import datetime, timedelta

import pytest

from sync import presence


def _write_foreign_lock(folder, user, host="OTHER-PC", age_sec=0):
    """他のPCが置いたロックを模擬する。"""
    beat = (datetime.now() - timedelta(seconds=age_sec)).isoformat(timespec="seconds")
    (folder / f"{user}.lock").write_text(json.dumps({
        "host": host, "pid": 1, "user": user, "started": beat, "heartbeat": beat,
    }), encoding="utf-8")


@pytest.fixture
def folder(tmp_path):
    """前田.db・山田.db がある共有フォルダ。"""
    import database as db
    orig = db.DB_PATH
    try:
        for name, worker in (("前田", "前田嘉正"), ("山田", "南部裕彩")):
            db.DB_PATH = tmp_path / f"{name}.db"
            db.init_db()
            db.add_worker(worker)
    finally:
        db.DB_PATH = orig
    return tmp_path


class TestLock:
    def test_acquire_and_release(self, folder):
        presence.acquire(folder, "山田")
        lock = presence.read_lock(folder, "山田")
        assert lock is not None and presence.is_mine(lock)
        assert "山田" in presence.active_users(folder)
        presence.release(folder, "山田")
        assert not (folder / "山田.lock").exists()

    def test_release_keeps_other_pcs_lock(self, folder):
        _write_foreign_lock(folder, "前田")
        presence.release(folder, "前田")
        assert (folder / "前田.lock").exists()

    def test_heartbeat_does_not_steal_other_pcs_lock(self, folder):
        _write_foreign_lock(folder, "前田")
        presence.heartbeat(folder, "前田")
        assert presence.read_lock(folder, "前田")["host"] == "OTHER-PC"

    def test_stale_lock_ignored(self, folder):
        _write_foreign_lock(folder, "前田", age_sec=presence.STALE_SEC + 10)
        assert presence.read_lock(folder, "前田") is None
        assert presence.active_users(folder) == {}

    def test_broken_lock_ignored(self, folder):
        (folder / "前田.lock").write_text("壊れた", encoding="utf-8")
        assert presence.read_lock(folder, "前田") is None


class TestListUsers:
    def test_lists_db_files_with_summary(self, folder):
        _write_foreign_lock(folder, "前田")
        users = {u["name"]: u for u in presence.list_users(folder)}
        assert set(users) == {"前田", "山田"}
        assert users["前田"]["workers"] == ["前田嘉正"]
        assert users["前田"]["lock"]["host"] == "OTHER-PC"
        assert users["山田"]["lock"] is None
        # .lock ファイルはユーザーとして数えない
        assert len(users) == 2


class TestUserSelectDialog:
    def _dialog(self, folder, monkeypatch, last_user=""):
        import database as db
        from ui.user_select_dialog import UserSelectDialog
        monkeypatch.setattr(db, "get_user_name", lambda: last_user)
        return UserSelectDialog(folder)

    def _names(self, dlg):
        from PyQt5.QtCore import Qt
        return [dlg._list.item(i).data(Qt.UserRole) for i in range(dlg._list.count())]

    def test_preselects_last_user(self, qapp, folder, monkeypatch):
        dlg = self._dialog(folder, monkeypatch, last_user="山田")
        assert self._names(dlg) == ["前田", "山田"]
        assert dlg._list.currentRow() == 1

    def test_select_free_user(self, qapp, folder, monkeypatch):
        dlg = self._dialog(folder, monkeypatch)
        dlg._list.setCurrentRow(1)
        dlg._accept_selected()
        assert dlg.selected_user() == "山田"
        assert dlg.result() == dlg.Accepted

    def test_in_use_user_shown_and_confirmed(self, qapp, folder, monkeypatch):
        from PyQt5.QtWidgets import QMessageBox
        _write_foreign_lock(folder, "前田")
        dlg = self._dialog(folder, monkeypatch)
        assert "使用中" in dlg._list.item(0).text()
        assert "OTHER-PC" in dlg._list.item(0).text()

        dlg._list.setCurrentRow(0)
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.No)
        dlg._accept_selected()
        assert dlg.selected_user() == ""          # いいえ → 開かない

        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)
        dlg._accept_selected()
        assert dlg.selected_user() == "前田"

    def test_add_new_user(self, qapp, folder, monkeypatch):
        from PyQt5.QtWidgets import QInputDialog
        dlg = self._dialog(folder, monkeypatch)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("佐藤", True))
        dlg._add_user()
        assert dlg.selected_user() == "佐藤"

    def test_add_user_rejects_invalid_name(self, qapp, folder, monkeypatch):
        from PyQt5.QtWidgets import QInputDialog, QMessageBox
        dlg = self._dialog(folder, monkeypatch)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("a/b", True))
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
        dlg._add_user()
        assert dlg.selected_user() == ""
