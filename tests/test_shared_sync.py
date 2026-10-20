"""共有フォルダ（複数ユーザーDB）まわりのテスト。
自分のDBと他ユーザーのDBを一時フォルダに作り、ガントチャートのチーム表示を検証する。
"""
import sqlite3

import pytest


def _make_other_db(path, worker="前田嘉正", task="平面", date="2026-10-26"):
    """他ユーザーのDBを、そのユーザーのアプリが作るのと同じスキーマで作成する。"""
    import database as db
    orig = db.DB_PATH
    db.DB_PATH = path
    try:
        db.init_db()
        wid = db.add_worker(worker)
        tid = db.add_task(task)
        db.add_schedule(wid, tid, date, 8.0)
    finally:
        db.DB_PATH = orig


@pytest.fixture
def shared_env(tmp_path, monkeypatch):
    """tmp_path を共有フォルダとし、自DB=山田.db・他ユーザーDB=前田.db を用意する。"""
    import database as db
    from sync.cache import shared_cache

    monkeypatch.setattr(db, "get_shared_folder", lambda: tmp_path)
    monkeypatch.setattr(db, "_JOURNAL_MODE", "DELETE")   # 共有フォルダ内DBの実運用と同じ
    _make_other_db(tmp_path / "前田.db")
    own = tmp_path / "山田.db"
    monkeypatch.setattr(db, "DB_PATH", own)
    db.init_db()

    shared_cache._snapshots.clear()
    yield db, tmp_path
    shared_cache._snapshots.clear()


def _load_all(folder):
    from sync.reader import load_db_snapshot
    from sync.cache import shared_cache
    for f in sorted(folder.glob("*.db")):
        snap = load_db_snapshot(f)
        assert snap is not None
        shared_cache.update(f, snap)


class TestSharedFolderDetection:
    def test_db_in_shared_folder(self, shared_env):
        db, _ = shared_env
        assert db.is_db_in_shared_folder()
        assert db._resolve_journal_mode() == "DELETE"

    def test_db_outside_shared_folder(self, shared_env, tmp_path_factory, monkeypatch):
        db, _ = shared_env
        monkeypatch.setattr(db, "DB_PATH", tmp_path_factory.mktemp("local") / "schedule.db")
        assert not db.is_db_in_shared_folder()
        assert db._resolve_journal_mode() == "WAL"


class TestCache:
    def test_tasks_are_tagged_with_source(self, shared_env):
        _, folder = shared_env
        _load_all(folder)
        from sync.cache import shared_cache
        tasks = shared_cache.get_all_tasks()
        assert [(t["_source"], t["title"]) for t in tasks] == [("前田", "平面")]
        assert tasks[0]["_uid"] == f"前田:{tasks[0]['id']}"


class TestGanttTeamView:
    def _tab(self, qapp, db):
        from PyQt5.QtCore import QDate
        from ui.gantt_tab import GanttTab
        tab = GanttTab()
        tab.from_date.setDate(QDate(2026, 10, 19))
        tab.to_date.setDate(QDate(2026, 10, 31))
        return tab

    def test_other_user_rows_shown_read_only(self, qapp, shared_env):
        db, folder = shared_env
        wid = db.add_worker("南部裕彩")
        tid = db.add_task("BIM練習")
        db.add_schedule(wid, tid, "2026-10-21", 4.0)
        _load_all(folder)

        tab = self._tab(qapp, db)
        tab.refresh()

        rows = [(r["worker"]["name"], r["task"]["title"], tab._row_readonly(i))
                for i, r in enumerate(tab._rows)]
        # 自分の行が先、他ユーザー行は末尾に読み取り専用で並ぶ（自DBは重複表示しない）
        assert rows == [("南部裕彩", "BIM練習", False), ("前田嘉正", "平面", True)]
        assert tab.fixed_table.item(1, 2).text() == "8.0"
        # 他ユーザーの行は保存対象の行順に入らない
        assert all(isinstance(w, int) for w, _ in tab._row_order)

    def test_ids_do_not_collide(self, qapp, shared_env):
        """自DBと他DBで worker_id/task_id が同じ 1 でも別の行になる。"""
        db, folder = shared_env
        wid = db.add_worker("南部裕彩")
        tid = db.add_task("BIM練習")
        assert (wid, tid) == (1, 1)
        db.add_schedule(wid, tid, "2026-10-26", 2.0)
        _load_all(folder)

        tab = self._tab(qapp, db)
        tab.refresh()
        assert tab.fixed_table.item(0, 2).text() == "2.0"
        assert tab.fixed_table.item(1, 2).text() == "8.0"

    def test_team_toggle_off(self, qapp, shared_env):
        db, folder = shared_env
        _load_all(folder)
        tab = self._tab(qapp, db)
        tab.team_chk.setChecked(False)
        tab.refresh()
        assert tab._rows == []

    def test_filter_other_user(self, qapp, shared_env):
        db, folder = shared_env
        wid = db.add_worker("南部裕彩")
        tid = db.add_task("BIM練習")
        db.add_schedule(wid, tid, "2026-10-21", 4.0)
        _load_all(folder)
        tab = self._tab(qapp, db)
        tab.refresh()

        idx = tab.worker_filter.findText("前田嘉正（前田）")
        assert idx >= 0
        tab.worker_filter.setCurrentIndex(idx)
        tab.refresh()
        assert [r["worker"]["name"] for r in tab._rows] == ["前田嘉正"]
        # 絞り込み中も自分の行は行順から消えない
        assert (wid, tid) in tab._row_order

    def test_other_db_never_written(self, qapp, shared_env):
        db, folder = shared_env
        import gc
        other = folder / "前田.db"
        gc.collect()   # 作成時の未closeの接続を確実に閉じてから比較する
        before = other.read_bytes()
        _load_all(folder)
        tab = self._tab(qapp, db)
        tab.refresh()
        tab._open_range_dialog(0, 0, 3)     # 読み取り専用行 → 何もしない
        tab._open_actual_inline(0, 0)
        assert other.read_bytes() == before
        conn = sqlite3.connect(other)
        assert conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0] == 1
        conn.close()
