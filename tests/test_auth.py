"""管理者・ユーザーのパスワード（sync/auth.py）と、管理者ログイン・編集対象切替のテスト。"""
import json

import pytest

from sync import auth


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """前田.db・山田.db がある共有フォルダ。設定ファイルも一時ファイルに差し替える。"""
    import database as db
    cfg_dir = tmp_path / "config"
    monkeypatch.setattr(db, "_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(db, "_CONFIG_FILE", cfg_dir / "config.json")
    # セッション・DBパス・ジャーナルモードはモジュール状態なので、テスト後に元へ戻す
    for name in ("DB_PATH", "_JOURNAL_MODE", "_SESSION_USER", "_IS_ADMIN"):
        monkeypatch.setattr(db, name, getattr(db, name))
    shared = tmp_path / "shared"
    shared.mkdir()
    orig = db.DB_PATH
    try:
        for name, worker in (("前田", "前田嘉正"), ("山田", "南部裕彩")):
            db.DB_PATH = shared / f"{name}.db"
            db.init_db()
            db.add_worker(worker)
    finally:
        db.DB_PATH = orig
    db.set_shared_folder(shared)
    return shared


class TestHash:
    def test_verify(self):
        h = auth.hash_password("秘密pass")
        assert auth.verify_password("秘密pass", h)
        assert not auth.verify_password("違う", h)

    def test_salted(self):
        assert auth.hash_password("x") != auth.hash_password("x")

    def test_broken_hash(self):
        assert not auth.verify_password("x", "壊れた値")


class TestAdmin:
    def test_default_admin_created(self, folder):
        auth.ensure_admin(folder)
        assert auth.verify_admin(folder, "admin")
        assert auth.admin_must_change(folder)
        # 平文で保存しない
        assert "admin" not in json.loads((folder / auth.ADMIN_FILE).read_text("utf-8"))["password"]

    def test_ensure_does_not_overwrite(self, folder):
        auth.ensure_admin(folder)
        auth.set_admin_password(folder, "新しいPW")
        auth.ensure_admin(folder)
        assert auth.verify_admin(folder, "新しいPW")
        assert not auth.verify_admin(folder, "admin")
        assert not auth.admin_must_change(folder)


class TestUserPassword:
    def test_no_password_by_default(self, folder):
        p = folder / "前田.db"
        assert not auth.user_has_password(p)
        assert auth.verify_user(p, "")

    def test_set_and_clear(self, folder):
        p = folder / "前田.db"
        auth.set_user_password(p, "maeda")
        assert auth.user_has_password(p)
        assert auth.verify_user(p, "maeda")
        assert not auth.verify_user(p, "x")
        auth.set_user_password(p, "")
        assert not auth.user_has_password(p)

    def test_missing_db(self, folder):
        assert not auth.user_has_password(folder / "いない.db")


class TestLoginDialog:
    def _dialog(self, folder):
        from ui.user_select_dialog import UserSelectDialog
        return UserSelectDialog(folder)

    def _row(self, dlg, key):
        from PyQt5.QtCore import Qt
        for i in range(dlg._list.count()):
            if dlg._list.item(i).data(Qt.UserRole) == key:
                return i
        raise AssertionError(key)

    def test_admin_listed_first(self, qapp, folder):
        dlg = self._dialog(folder)
        assert "管理者" in dlg._list.item(0).text()
        assert "初期パスワード: admin" in dlg._list.item(0).text()
        assert (folder / auth.ADMIN_FILE).exists()

    def test_admin_first_login_forces_change(self, qapp, folder, monkeypatch):
        import ui.user_select_dialog as m
        dlg = self._dialog(folder)
        monkeypatch.setattr(m, "ask_password", lambda *a: "admin")
        monkeypatch.setattr(m.PasswordChangeDialog, "exec_", lambda self: m.QDialog.Accepted)
        monkeypatch.setattr(m.PasswordChangeDialog, "password", lambda self: "kanri123")
        dlg._list.setCurrentRow(0)
        dlg._accept_selected()
        assert dlg.is_admin()
        assert dlg.selected_user() in ("前田", "山田")
        assert auth.verify_admin(folder, "kanri123")
        assert not auth.admin_must_change(folder)

    def test_admin_change_cancel_aborts_login(self, qapp, folder, monkeypatch):
        import ui.user_select_dialog as m
        dlg = self._dialog(folder)
        monkeypatch.setattr(m, "ask_password", lambda *a: "admin")
        monkeypatch.setattr(m.PasswordChangeDialog, "exec_", lambda self: m.QDialog.Rejected)
        dlg._list.setCurrentRow(0)
        dlg._accept_selected()
        assert not dlg.is_admin()
        assert dlg.result() != dlg.Accepted

    def test_admin_wrong_password(self, qapp, folder, monkeypatch):
        import ui.user_select_dialog as m
        dlg = self._dialog(folder)
        monkeypatch.setattr(m, "ask_password", lambda *a: "違う")
        monkeypatch.setattr(m.QMessageBox, "warning", lambda *a, **k: m.QMessageBox.Ok)
        dlg._list.setCurrentRow(0)
        dlg._accept_selected()
        assert not dlg.is_admin()

    def test_user_with_password(self, qapp, folder, monkeypatch):
        import ui.user_select_dialog as m
        auth.set_user_password(folder / "前田.db", "maeda")
        dlg = self._dialog(folder)
        assert "🔒" in dlg._list.item(self._row(dlg, "前田")).text()
        dlg._list.setCurrentRow(self._row(dlg, "前田"))

        monkeypatch.setattr(m.QMessageBox, "warning", lambda *a, **k: m.QMessageBox.Ok)
        monkeypatch.setattr(m, "ask_password", lambda *a: "違う")
        dlg._accept_selected()
        assert dlg.selected_user() == ""

        monkeypatch.setattr(m, "ask_password", lambda *a: "maeda")
        dlg._accept_selected()
        assert dlg.selected_user() == "前田"
        assert not dlg.is_admin()

    def test_user_without_password_opens_directly(self, qapp, folder, monkeypatch):
        import ui.user_select_dialog as m
        monkeypatch.setattr(m, "ask_password",
                            lambda *a: pytest.fail("パスワード未設定なのに入力を求めた"))
        dlg = self._dialog(folder)
        dlg._list.setCurrentRow(self._row(dlg, "山田"))
        dlg._accept_selected()
        assert dlg.selected_user() == "山田"

    def test_new_user_with_password(self, qapp, folder, monkeypatch):
        import ui.user_select_dialog as m
        dlg = self._dialog(folder)
        monkeypatch.setattr(m.QInputDialog, "getText", lambda *a, **k: ("佐藤", True))
        monkeypatch.setattr(m.PasswordChangeDialog, "exec_", lambda self: m.QDialog.Accepted)
        monkeypatch.setattr(m.PasswordChangeDialog, "password", lambda self: "sato")
        dlg._add_user()
        assert dlg.selected_user() == "佐藤"
        assert dlg.new_user_password() == "sato"

    def test_admin_name_reserved(self, qapp, folder, monkeypatch):
        import ui.user_select_dialog as m
        dlg = self._dialog(folder)
        monkeypatch.setattr(m.QInputDialog, "getText", lambda *a, **k: ("管理者", True))
        monkeypatch.setattr(m.QMessageBox, "warning", lambda *a, **k: m.QMessageBox.Ok)
        dlg._add_user()
        assert dlg.selected_user() == ""


class TestPasswordChangeDialog:
    def test_mismatch_rejected(self, qapp, monkeypatch):
        import ui.password_dialogs as m
        monkeypatch.setattr(m.QMessageBox, "warning", lambda *a, **k: m.QMessageBox.Ok)
        dlg = m.PasswordChangeDialog()
        dlg._new.setText("a"); dlg._confirm.setText("b")
        dlg._accept()
        assert dlg.result() != dlg.Accepted

    def test_forbidden_and_empty(self, qapp, monkeypatch):
        import ui.password_dialogs as m
        monkeypatch.setattr(m.QMessageBox, "warning", lambda *a, **k: m.QMessageBox.Ok)
        dlg = m.PasswordChangeDialog(allow_empty=False, forbidden={"admin"})
        dlg._new.setText("admin"); dlg._confirm.setText("admin")
        dlg._accept()
        assert dlg.result() != dlg.Accepted
        dlg._new.setText(""); dlg._confirm.setText("")
        dlg._accept()
        assert dlg.result() != dlg.Accepted

    def test_current_password_checked(self, qapp, monkeypatch):
        import ui.password_dialogs as m
        monkeypatch.setattr(m.QMessageBox, "warning", lambda *a, **k: m.QMessageBox.Ok)
        dlg = m.PasswordChangeDialog(verify_current=lambda pw: pw == "old")
        dlg._current.setText("x"); dlg._new.setText("n"); dlg._confirm.setText("n")
        dlg._accept()
        assert dlg.result() != dlg.Accepted
        dlg._current.setText("old")
        dlg._accept()
        assert dlg.result() == dlg.Accepted and dlg.password() == "n"


class TestAdminSession:
    def test_session_does_not_overwrite_pc_user(self, folder):
        import database as db
        db.set_user_name("山田")
        db.set_session("前田", admin=True)
        assert db.DB_PATH == folder / "前田.db"
        assert db.get_current_user() == "前田"
        assert db.get_user_name() == "山田"      # このPCの利用者設定はそのまま
        db.set_session(None)
        assert db.DB_PATH == folder / "山田.db"

    def test_main_window_switches_target(self, qapp, folder):
        import database as db
        from ui.main_window import MainWindow
        from sync import presence
        db.set_session("前田", admin=True)
        db.init_db()
        w = MainWindow()
        try:
            assert "管理者" in w.windowTitle() and "前田" in w.windowTitle()
            assert [w._target_combo.itemText(i) for i in range(w._target_combo.count())] == ["前田", "山田"]
            assert presence.read_lock(folder, "前田")["admin"] is True

            db._undo_stack.append([{"op": "dummy"}])   # 前田DBの戻る履歴があるとする
            assert db.can_undo()
            w._on_target_selected("山田")

            assert db.DB_PATH == folder / "山田.db"
            assert not db.can_undo()                         # 前のDBの履歴は破棄
            assert presence.read_lock(folder, "前田") is None  # 前の対象のロックは解放
            assert presence.read_lock(folder, "山田")["admin"] is True
            names = [r["worker"]["name"] for r in w.gantt_tab._rows if not r["worker"].get("_readonly")]
            assert all(n == "南部裕彩" for n in names)
            assert "山田" in w.windowTitle()
        finally:
            if w._watcher:
                w._watcher.stop()
            w._stop_presence()
