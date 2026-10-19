"""database.py の単体テスト。
temp_db フィクスチャで一時 DB を使い、モジュール間の副作用を排除する。
"""
import pytest


# ── Workers ──────────────────────────────────────────────────────────────────

class TestWorkers:
    def test_add_and_get(self, temp_db):
        db = temp_db
        wid = db.add_worker("山田 太郎", "開発部")
        workers = db.get_all_workers()
        assert len(workers) == 1
        assert workers[0]["name"] == "山田 太郎"
        assert workers[0]["department"] == "開発部"
        assert workers[0]["id"] == wid

    def test_update(self, temp_db):
        db = temp_db
        wid = db.add_worker("旧名")
        db.update_worker(wid, "新名", "新部署")
        workers = db.get_all_workers()
        assert workers[0]["name"] == "新名"
        assert workers[0]["department"] == "新部署"

    def test_delete(self, temp_db):
        db = temp_db
        wid = db.add_worker("削除対象")
        db.delete_worker(wid)
        assert db.get_all_workers() == []

    def test_multiple_workers_ordered_by_name(self, temp_db):
        db = temp_db
        db.add_worker("鈴木")
        db.add_worker("田中")
        db.add_worker("安倍")
        names = [w["name"] for w in db.get_all_workers()]
        assert names == sorted(names)

    def test_empty_department_default(self, temp_db):
        db = temp_db
        db.add_worker("名前のみ")
        assert db.get_all_workers()[0]["department"] == ""


# ── Tasks ─────────────────────────────────────────────────────────────────────

class TestTasks:
    def test_add_and_get(self, temp_db):
        db = temp_db
        tid = db.add_task("テスト作業", "説明", "カテゴリ")
        tasks = db.get_all_tasks()
        assert len(tasks) == 1
        assert tasks[0]["title"] == "テスト作業"
        assert tasks[0]["id"] == tid

    def test_update(self, temp_db):
        db = temp_db
        tid = db.add_task("旧タスク")
        db.update_task(tid, "新タスク", "新説明", "新カテゴリ")
        t = db.get_all_tasks()[0]
        assert t["title"] == "新タスク"
        assert t["description"] == "新説明"
        assert t["category"] == "新カテゴリ"

    def test_delete(self, temp_db):
        db = temp_db
        tid = db.add_task("消えるタスク")
        db.delete_task(tid)
        assert db.get_all_tasks() == []

    def test_title_only_defaults(self, temp_db):
        db = temp_db
        db.add_task("最小タスク")
        t = db.get_all_tasks()[0]
        assert t["description"] == ""
        assert t["category"] == ""


# ── Schedules ─────────────────────────────────────────────────────────────────

class TestSchedules:
    @pytest.fixture
    def worker_task(self, temp_db):
        db = temp_db
        wid = db.add_worker("テスト担当者")
        tid = db.add_task("テスト作業")
        return db, wid, tid

    def test_add_and_get(self, worker_task):
        db, wid, tid = worker_task
        sid = db.add_schedule(wid, tid, "2026-10-05", 8.0, "planned", "メモ")
        rows = db.get_schedules()
        assert len(rows) == 1
        assert rows[0]["scheduled_date"] == "2026-10-05"
        assert rows[0]["scheduled_hours"] == 8.0
        assert rows[0]["status"] == "planned"
        assert rows[0]["note"] == "メモ"
        assert rows[0]["id"] == sid

    def test_filter_by_worker(self, temp_db):
        db = temp_db
        wid1 = db.add_worker("担当A")
        wid2 = db.add_worker("担当B")
        tid  = db.add_task("作業")
        db.add_schedule(wid1, tid, "2026-10-05", 8.0)
        db.add_schedule(wid2, tid, "2026-10-06", 8.0)
        rows = db.get_schedules(worker_id=wid1)
        assert len(rows) == 1
        assert rows[0]["worker_id"] == wid1

    def test_filter_by_date_range(self, worker_task):
        db, wid, tid = worker_task
        db.add_schedule(wid, tid, "2026-10-01", 8.0)
        db.add_schedule(wid, tid, "2026-10-10", 8.0)
        db.add_schedule(wid, tid, "2026-10-20", 8.0)
        rows = db.get_schedules(date_from="2026-10-05", date_to="2026-10-15")
        assert len(rows) == 1
        assert rows[0]["scheduled_date"] == "2026-10-10"

    def test_update(self, worker_task):
        db, wid, tid = worker_task
        sid = db.add_schedule(wid, tid, "2026-10-05", 8.0)
        db.update_schedule(sid, wid, tid, "2026-10-06", 4.0, "in_progress", "更新")
        rows = db.get_schedules()
        assert rows[0]["scheduled_date"] == "2026-10-06"
        assert rows[0]["scheduled_hours"] == 4.0
        assert rows[0]["status"] == "in_progress"
        assert rows[0]["note"] == "更新"

    def test_delete(self, worker_task):
        db, wid, tid = worker_task
        sid = db.add_schedule(wid, tid, "2026-10-05", 8.0)
        db.delete_schedule(sid)
        assert db.get_schedules() == []

    def test_get_by_id(self, worker_task):
        db, wid, tid = worker_task
        sid = db.add_schedule(wid, tid, "2026-10-05", 8.0)
        row = db.get_schedule_by_id(sid)
        assert row is not None
        assert row["id"] == sid

    def test_get_by_id_not_found(self, temp_db):
        db = temp_db
        assert db.get_schedule_by_id(9999) is None

    def test_cascade_delete_with_worker(self, worker_task):
        db, wid, tid = worker_task
        db.add_schedule(wid, tid, "2026-10-05", 8.0)
        db.delete_worker(wid)
        assert db.get_schedules() == []


# ── Actuals ───────────────────────────────────────────────────────────────────

class TestActuals:
    @pytest.fixture
    def base(self, temp_db):
        db = temp_db
        wid = db.add_worker("実績担当者")
        tid = db.add_task("実績作業")
        sid = db.add_schedule(wid, tid, "2026-10-05", 8.0)
        return db, wid, tid, sid

    def test_add_and_get(self, base):
        db, wid, tid, sid = base
        aid = db.add_actual(wid, tid, "2026-10-05", 7.5, schedule_id=sid, note="完了")
        rows = db.get_actuals()
        assert len(rows) == 1
        assert rows[0]["actual_hours"] == 7.5
        assert rows[0]["note"] == "完了"
        assert rows[0]["id"] == aid

    def test_filter_by_worker(self, temp_db):
        db = temp_db
        wid1 = db.add_worker("担当A")
        wid2 = db.add_worker("担当B")
        tid  = db.add_task("作業")
        db.add_actual(wid1, tid, "2026-10-05", 8.0)
        db.add_actual(wid2, tid, "2026-10-05", 8.0)
        rows = db.get_actuals(worker_id=wid1)
        assert len(rows) == 1

    def test_filter_by_date_range(self, base):
        db, wid, tid, sid = base
        db.add_actual(wid, tid, "2026-10-01", 8.0)
        db.add_actual(wid, tid, "2026-10-10", 8.0)
        db.add_actual(wid, tid, "2026-10-20", 8.0)
        rows = db.get_actuals(date_from="2026-10-05", date_to="2026-10-15")
        assert len(rows) == 1
        assert rows[0]["actual_date"] == "2026-10-10"

    def test_update(self, base):
        db, wid, tid, sid = base
        aid = db.add_actual(wid, tid, "2026-10-05", 7.5)
        db.update_actual(aid, wid, tid, "2026-10-05", 6.0, "変更後")
        rows = db.get_actuals()
        assert rows[0]["actual_hours"] == 6.0
        assert rows[0]["note"] == "変更後"

    def test_delete(self, base):
        db, wid, tid, sid = base
        aid = db.add_actual(wid, tid, "2026-10-05", 7.5)
        db.delete_actual(aid)
        assert db.get_actuals() == []

    def test_get_by_id(self, base):
        db, wid, tid, sid = base
        aid = db.add_actual(wid, tid, "2026-10-05", 7.5)
        row = db.get_actual_by_id(aid)
        assert row is not None
        assert row["id"] == aid

    def test_get_by_id_not_found(self, temp_db):
        db = temp_db
        assert db.get_actual_by_id(9999) is None


# ── Settings ──────────────────────────────────────────────────────────────────

class TestSettings:
    def test_set_and_get(self, temp_db):
        db = temp_db
        db.set_setting("test_key", "test_value")
        assert db.get_setting("test_key") == "test_value"

    def test_missing_key_returns_default(self, temp_db):
        db = temp_db
        assert db.get_setting("no_such_key") == ""
        assert db.get_setting("no_such_key", "fallback") == "fallback"

    def test_overwrite(self, temp_db):
        db = temp_db
        db.set_setting("k", "v1")
        db.set_setting("k", "v2")
        assert db.get_setting("k") == "v2"

    def test_task_text_colors(self, temp_db):
        db = temp_db
        db.set_task_text_color(1, "#FF0000")
        colors = db.get_task_text_colors()
        assert colors["1"] == "#FF0000"

    def test_task_text_color_reset(self, temp_db):
        db = temp_db
        db.set_task_text_color(1, "#FF0000")
        db.set_task_text_color(1, "")   # リセット
        colors = db.get_task_text_colors()
        assert "1" not in colors


# ── Undo / Redo ───────────────────────────────────────────────────────────────

class TestUndoRedo:
    @pytest.fixture
    def wt(self, temp_db):
        db = temp_db
        wid = db.add_worker("Undo担当")
        tid = db.add_task("Undo作業")
        return db, wid, tid

    def test_can_undo_after_add(self, wt):
        db, wid, tid = wt
        db.add_schedule(wid, tid, "2026-10-05", 8.0)
        assert db.can_undo()

    def test_undo_removes_added_schedule(self, wt):
        db, wid, tid = wt
        db.add_schedule(wid, tid, "2026-10-05", 8.0)
        db.do_undo()
        assert db.get_schedules() == []

    def test_redo_restores_schedule(self, wt):
        db, wid, tid = wt
        db.add_schedule(wid, tid, "2026-10-05", 8.0)
        db.do_undo()
        assert db.can_redo()
        db.do_redo()
        assert len(db.get_schedules()) == 1

    def test_begin_end_action_groups_ops(self, wt):
        db, wid, tid = wt
        db.begin_action()
        db.add_schedule(wid, tid, "2026-10-05", 8.0)
        db.add_schedule(wid, tid, "2026-10-06", 8.0)
        db.end_action()
        assert len(db._undo_stack) == 1   # 1 グループ
        db.do_undo()
        assert db.get_schedules() == []   # 2件まとめてUndoされる

    def test_undo_empty_stack_returns_false(self, temp_db):
        assert temp_db.do_undo() is False

    def test_redo_empty_stack_returns_false(self, temp_db):
        assert temp_db.do_redo() is False

    def test_redo_cleared_after_new_op(self, wt):
        db, wid, tid = wt
        db.add_schedule(wid, tid, "2026-10-05", 8.0)
        db.do_undo()
        db.add_schedule(wid, tid, "2026-10-06", 8.0)
        assert not db.can_redo()

    def test_undo_stack_max_50(self, wt):
        db, wid, tid = wt
        for i in range(55):
            db.add_schedule(wid, tid, f"2026-10-{i+1:02d}" if i < 31 else f"2026-11-{i-30:02d}", 1.0)
        assert len(db._undo_stack) <= 50


# ── Snapshots ─────────────────────────────────────────────────────────────────

class TestSnapshots:
    @pytest.fixture
    def with_data(self, temp_db):
        db = temp_db
        wid = db.add_worker("スナップ担当")
        tid = db.add_task("スナップ作業")
        db.add_schedule(wid, tid, "2026-10-05", 8.0)
        return db

    def test_save_and_get(self, with_data):
        db = with_data
        db.save_snapshot("2026-10-05")
        snap = db.get_snapshot("2026-10-05")
        assert snap is not None
        assert snap["snapshot_date"] == "2026-10-05"
        assert len(snap["schedules"]) == 1

    def test_get_nonexistent_returns_none(self, temp_db):
        assert temp_db.get_snapshot("9999-01-01") is None

    def test_overwrite_same_date(self, with_data):
        db = with_data
        db.save_snapshot("2026-10-05")
        wid2 = db.add_worker("追加担当")
        tid2 = db.add_task("追加作業")
        db.add_schedule(wid2, tid2, "2026-10-05", 4.0)
        db.save_snapshot("2026-10-05")
        snap = db.get_snapshot("2026-10-05")
        assert len(snap["schedules"]) == 2

    def test_get_snapshot_dates_descending(self, with_data):
        db = with_data
        db.save_snapshot("2026-10-01")
        db.save_snapshot("2026-10-05")
        db.save_snapshot("2026-10-03")
        dates = db.get_snapshot_dates()
        assert dates == sorted(dates, reverse=True)

    def test_auto_save_today_only_once(self, with_data):
        db = with_data
        from datetime import date
        today = date.today().strftime("%Y-%m-%d")
        db.auto_save_today_snapshot()
        db.auto_save_today_snapshot()   # 2回目は何もしない
        assert db.get_snapshot_dates().count(today) == 1

    def test_delete_snapshot(self, with_data):
        db = with_data
        db.save_snapshot("2026-10-05")
        db.delete_snapshot("2026-10-05")
        assert db.get_snapshot("2026-10-05") is None


# ── Summary ───────────────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_by_worker(self, temp_db):
        db = temp_db
        wid = db.add_worker("集計担当")
        tid = db.add_task("集計作業")
        db.add_schedule(wid, tid, "2026-10-05", 8.0)
        db.add_schedule(wid, tid, "2026-10-06", 4.0)
        db.add_actual(wid, tid, "2026-10-05", 7.5)

        summary = db.get_summary_by_worker()
        row = next(r for r in summary if r["name"] == "集計担当")
        assert row["scheduled"] == 12.0
        assert row["actual"] == 7.5

    def test_summary_date_filter(self, temp_db):
        db = temp_db
        wid = db.add_worker("フィルタ担当")
        tid = db.add_task("フィルタ作業")
        db.add_schedule(wid, tid, "2026-09-30", 8.0)
        db.add_schedule(wid, tid, "2026-10-05", 8.0)
        summary = db.get_summary_by_worker(date_from="2026-10-01")
        row = next(r for r in summary if r["name"] == "フィルタ担当")
        assert row["scheduled"] == 8.0


# ── Schema version ────────────────────────────────────────────────────────────

class TestSchemaVersion:
    def test_schema_version_recorded(self, temp_db):
        db = temp_db
        ver = db.get_db_schema_version()
        assert isinstance(ver, int)
        assert ver >= 1

    def test_compatibility_ok_for_same_version(self, temp_db):
        db = temp_db
        ok, msg = db.check_schema_compatibility()
        assert ok
        assert msg == ""

    def test_incompatible_when_db_newer(self, temp_db, monkeypatch):
        db = temp_db
        # DB のスキーマバージョンをアプリより大きくする
        db.set_setting("db_schema_version", "9999")
        ok, msg = db.check_schema_compatibility()
        assert not ok
        assert "9999" in msg


# ── Reset ─────────────────────────────────────────────────────────────────────

class TestResetDb:
    def test_reset_clears_all_data(self, temp_db):
        db = temp_db
        wid = db.add_worker("消す担当")
        tid = db.add_task("消す作業")
        db.add_schedule(wid, tid, "2026-10-05", 8.0)
        db.reset_db()
        assert db.get_all_workers() == []
        assert db.get_all_tasks() == []
        assert db.get_schedules() == []


# ── History ───────────────────────────────────────────────────────────────────

class TestHistory:
    def test_get_history_returns_records(self, temp_db):
        db = temp_db
        db.add_worker("履歴担当")
        history = db.get_history()
        assert len(history) >= 1
        assert history[0]["action"] == "INSERT"

    def test_get_history_limit(self, temp_db):
        db = temp_db
        for i in range(5):
            db.add_worker(f"担当{i}")
        history = db.get_history(limit=3)
        assert len(history) == 3


# ── Undo / Redo の UPDATE / DELETE パス ──────────────────────────────────────

class TestUndoRedoUpdateDelete:
    @pytest.fixture
    def wt(self, temp_db):
        db = temp_db
        wid = db.add_worker("Undo担当2")
        tid = db.add_task("Undo作業2")
        return db, wid, tid

    def test_undo_redo_update(self, wt):
        db, wid, tid = wt
        sid = db.add_schedule(wid, tid, "2026-10-05", 8.0)
        db.update_schedule(sid, wid, tid, "2026-10-05", 4.0, "completed", "変更")
        # undo → 元に戻る
        db.do_undo()
        rows = db.get_schedules()
        assert rows[0]["scheduled_hours"] == 8.0
        # redo → 再適用
        db.do_redo()
        rows = db.get_schedules()
        assert rows[0]["scheduled_hours"] == 4.0

    def test_undo_redo_delete(self, wt):
        db, wid, tid = wt
        sid = db.add_schedule(wid, tid, "2026-10-05", 8.0)
        db.delete_schedule(sid)
        # undo → 復元
        db.do_undo()
        assert len(db.get_schedules()) == 1
        # redo → 再削除
        db.do_redo()
        assert db.get_schedules() == []

    def test_end_action_overflow_pops_oldest(self, wt):
        db, wid, tid = wt
        # begin_action/end_action のスタック上限テスト
        for i in range(52):
            db.begin_action()
            db.add_schedule(
                wid, tid,
                f"2026-10-{(i % 28) + 1:02d}", 1.0, note=f"n{i}",
            )
            db.end_action()
        assert len(db._undo_stack) <= 50


# ── get_summary_by_worker date_to ─────────────────────────────────────────────

class TestSummaryDateTo:
    def test_summary_with_date_to_filter(self, temp_db):
        db = temp_db
        wid = db.add_worker("集計2")
        tid = db.add_task("作業2")
        db.add_schedule(wid, tid, "2026-10-05", 8.0)
        db.add_schedule(wid, tid, "2026-10-20", 8.0)
        # date_to で 10/10 まで絞ると 10/05 の 8h のみ
        summary = db.get_summary_by_worker(date_to="2026-10-10")
        row = next(r for r in summary if r["name"] == "集計2")
        assert row["scheduled"] == 8.0


# ── get_task_text_colors 例外ハンドラ ─────────────────────────────────────────

class TestTaskTextColorsCorrupt:
    def test_corrupt_json_returns_empty_dict(self, temp_db):
        db = temp_db
        # settings に壊れた JSON を直接書き込む
        db.set_setting("task_text_colors", "NOT_VALID_JSON{{{")
        result = db.get_task_text_colors()
        assert result == {}
