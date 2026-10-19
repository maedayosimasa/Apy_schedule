import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def qapp():
    """セッション全体で共有する QApplication。"""
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """テスト専用のインメモリ相当の一時 DB を用意し、init_db() を実行する。
    各テストの開始時に DB ファイル・スタックをリセットする。"""
    import database as db
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init_db()
    db._undo_stack.clear()
    db._redo_stack.clear()
    db._current_group = None
    db._in_undo_redo = False
    return db
