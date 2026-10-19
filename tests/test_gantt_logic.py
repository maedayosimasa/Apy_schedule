"""ガントチャートのコアロジック単体テスト。
_nonwork_gap_only と _get_span_dates（今回修正した関数）を中心にテストする。
"""
from datetime import date
from unittest.mock import patch
import pytest


# ── _nonwork_gap_only ─────────────────────────────────────────────────────────

from ui.gantt_tab import _nonwork_gap_only


class TestNonworkGapOnly:
    # 2026-10 カレンダー:
    #   1(木) 2(金) 3(土) 4(日) 5(月) 6(火) 7(水) 8(木) 9(金)
    #   10(土)11(日)12(月=スポーツの日)13(火)14(水)15(木)16(金)
    #   17(土)18(日)19(月)

    def test_adjacent_work_days(self):
        # 隣接日は間がないので True
        assert _nonwork_gap_only(date(2026, 10, 5), date(2026, 10, 6)) is True

    def test_friday_to_monday_weekend_gap(self):
        # 金(10/2)→月(10/5): 間は土(3)・日(4) → True
        assert _nonwork_gap_only(date(2026, 10, 2), date(2026, 10, 5)) is True

    def test_single_work_day_gap(self):
        # 月(10/5)→水(10/7): 間に火(10/6=平日) → False
        assert _nonwork_gap_only(date(2026, 10, 5), date(2026, 10, 7)) is False

    def test_holiday_in_gap_passes(self):
        # 金(10/9)→火(10/13): 間に土(10)・日(11)・月(12=祝) → True
        assert _nonwork_gap_only(date(2026, 10, 9), date(2026, 10, 13)) is True

    def test_work_day_after_holiday_fails(self):
        # 金(10/9)→水(10/14): 間に土・日・月(祝)・火(10/13=平日) → False
        assert _nonwork_gap_only(date(2026, 10, 9), date(2026, 10, 14)) is False

    def test_same_day_adjacent(self):
        # d1+1 == d2 のとき間はゼロ → True
        assert _nonwork_gap_only(date(2026, 10, 1), date(2026, 10, 2)) is True

    def test_long_weekend_gap(self):
        # 金(10/16)→月(10/19): 土・日のみ → True
        assert _nonwork_gap_only(date(2026, 10, 16), date(2026, 10, 19)) is True

    def test_multiple_work_days_gap(self):
        # 月(10/5)→金(10/9): 火水木が平日 → False
        assert _nonwork_gap_only(date(2026, 10, 5), date(2026, 10, 9)) is False


# ── _get_span_dates ──────────────────────────────────────────────────────────
# db.get_schedules をモックして純粋なセグメント分割ロジックをテストする。

from ui.gantt_tab import GanttTab


def _call_span_dates(mock_scheds, worker_id, task_id, clicked):
    """GanttTab._get_span_dates を db.get_schedules モックで呼び出す。"""
    with patch("database.get_schedules", return_value=mock_scheds):
        return GanttTab._get_span_dates(None, worker_id, task_id, clicked)


def _sched(worker_id, task_id, date_str, note="", status="planned"):
    return {
        "worker_id": worker_id,
        "task_id": task_id,
        "scheduled_date": date_str,
        "note": note,
        "status": status,
    }


class TestGetSpanDatesSingleDay:
    def test_single_schedule_returns_one_date(self):
        s = [_sched(1, 1, "2026-10-05")]
        result = _call_span_dates(s, 1, 1, date(2026, 10, 5))
        assert result == [date(2026, 10, 5)]

    def test_no_schedules_returns_clicked(self):
        result = _call_span_dates([], 1, 1, date(2026, 10, 5))
        assert result == [date(2026, 10, 5)]

    def test_other_task_not_included(self):
        # task_id=2 の予定は対象外
        scheds = [
            _sched(1, 1, "2026-10-05"),
            _sched(1, 2, "2026-10-06"),  # 別タスク
        ]
        result = _call_span_dates(scheds, 1, 1, date(2026, 10, 5))
        assert result == [date(2026, 10, 5)]


class TestGetSpanDatesSegmentation:
    def test_adjacent_same_note_status_grouped(self):
        # 月(10/5)・火(10/6) 同じ note・status → 同一セグメント
        scheds = [
            _sched(1, 1, "2026-10-05", note="A", status="planned"),
            _sched(1, 1, "2026-10-06", note="A", status="planned"),
        ]
        result = _call_span_dates(scheds, 1, 1, date(2026, 10, 5))
        assert date(2026, 10, 5) in result
        assert date(2026, 10, 6) in result
        assert len(result) == 2

    def test_different_note_splits_segment(self):
        # 月(10/5) note=A、火(10/6) note=B → 別セグメント
        scheds = [
            _sched(1, 1, "2026-10-05", note="A"),
            _sched(1, 1, "2026-10-06", note="B"),
        ]
        result = _call_span_dates(scheds, 1, 1, date(2026, 10, 5))
        assert result == [date(2026, 10, 5)]

    def test_different_status_splits_segment(self):
        # 月(10/5) planned、火(10/6) completed → 別セグメント
        scheds = [
            _sched(1, 1, "2026-10-05", status="planned"),
            _sched(1, 1, "2026-10-06", status="completed"),
        ]
        result = _call_span_dates(scheds, 1, 1, date(2026, 10, 5))
        assert result == [date(2026, 10, 5)]

    def test_weekend_gap_same_segment(self):
        # 金(10/2)・月(10/5): 間に土日のみ → 同一セグメント
        scheds = [
            _sched(1, 1, "2026-10-02", note="A", status="planned"),
            _sched(1, 1, "2026-10-05", note="A", status="planned"),
        ]
        result = _call_span_dates(scheds, 1, 1, date(2026, 10, 2))
        assert len(result) == 2

    def test_work_day_gap_splits_segment(self):
        # 月(10/5)・水(10/7): 間に火曜=平日 → 別セグメント（note同じでも）
        scheds = [
            _sched(1, 1, "2026-10-05", note="A"),
            _sched(1, 1, "2026-10-07", note="A"),
        ]
        result = _call_span_dates(scheds, 1, 1, date(2026, 10, 5))
        assert result == [date(2026, 10, 5)]

    def test_holiday_gap_same_segment(self):
        # 金(10/9)・火(10/13): 間に土・日・月(祝) → 同一セグメント
        scheds = [
            _sched(1, 1, "2026-10-09", note="X", status="planned"),
            _sched(1, 1, "2026-10-13", note="X", status="planned"),
        ]
        result = _call_span_dates(scheds, 1, 1, date(2026, 10, 9))
        assert len(result) == 2


class TestGetSpanDatesMultipleSegments:
    def test_returns_correct_segment_when_multiple_exist(self):
        # セグメント1: 10/5, 10/6 (note=A)
        # セグメント2: 10/7, 10/8 (note=B)
        # 10/7 をクリック → セグメント2 のみ返る
        scheds = [
            _sched(1, 1, "2026-10-05", note="A"),
            _sched(1, 1, "2026-10-06", note="A"),
            _sched(1, 1, "2026-10-07", note="B"),
            _sched(1, 1, "2026-10-08", note="B"),
        ]
        result = _call_span_dates(scheds, 1, 1, date(2026, 10, 7))
        assert date(2026, 10, 7) in result
        assert date(2026, 10, 8) in result
        assert date(2026, 10, 5) not in result
        assert date(2026, 10, 6) not in result

    def test_oldest_date_not_selected_for_single_schedule(self):
        # バグ再現テスト:
        # 同じ担当者・作業に対して離れた日付の予定が複数ある場合、
        # 単体の予定 (10/19) をクリックしたとき最古日 (10/01) は含まれない
        scheds = [
            _sched(1, 1, "2026-10-01", note="過去A"),
            _sched(1, 1, "2026-10-02", note="過去A"),
            _sched(1, 1, "2026-10-19", note="今日B"),   # 別 note → 別セグメント
        ]
        result = _call_span_dates(scheds, 1, 1, date(2026, 10, 19))
        assert result == [date(2026, 10, 19)]
        assert date(2026, 10, 1) not in result

    def test_single_among_many_returns_only_itself(self):
        # 全て異なる note → それぞれ独立セグメント
        scheds = [
            _sched(1, 1, "2026-10-05", note="N1"),
            _sched(1, 1, "2026-10-06", note="N2"),
            _sched(1, 1, "2026-10-07", note="N3"),
        ]
        result = _call_span_dates(scheds, 1, 1, date(2026, 10, 6))
        assert result == [date(2026, 10, 6)]

    def test_three_day_span_middle_click(self):
        # 連続3日のスパン、中間をクリックしても全3日が返る
        scheds = [
            _sched(1, 1, "2026-10-05", note="A", status="planned"),
            _sched(1, 1, "2026-10-06", note="A", status="planned"),
            _sched(1, 1, "2026-10-07", note="A", status="planned"),
        ]
        result = _call_span_dates(scheds, 1, 1, date(2026, 10, 6))
        assert len(result) == 3
        assert sorted(result) == [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)]

    def test_clicked_date_not_in_any_group_returns_clicked(self):
        # clicked がどのグループにも属さない場合（DBに存在しない日）
        scheds = [_sched(1, 1, "2026-10-05", note="A")]
        result = _call_span_dates(scheds, 1, 1, date(2026, 10, 9))
        assert result == [date(2026, 10, 9)]
