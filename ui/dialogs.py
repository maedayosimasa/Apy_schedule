from datetime import date, timedelta
from PyQt5.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox,
    QDateEdit, QDialogButtonBox, QMessageBox, QLabel, QCheckBox,
    QCompleter, QCalendarWidget, QHBoxLayout, QVBoxLayout,
    QGroupBox, QGridLayout, QPushButton, QWidget, QApplication,
)
from PyQt5.QtCore import QDate, Qt, pyqtSignal, QRect
from PyQt5.QtGui import QDoubleValidator, QColor, QFont
import database as db

_HOURS_OPTIONS = [
    '0.5', '1.0', '1.5', '2.0', '2.5', '3.0', '3.5', '4.0',
    '4.5', '5.0', '5.5', '6.0', '6.5', '7.0', '7.5', '8.0',
    '9.0', '10.0', '12.0',
]


def _make_hours_combo(current: float = 8.0) -> QComboBox:
    """プルダウン＋直接入力に対応した時間コンボボックスを生成する。"""
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    for h in _HOURS_OPTIONS:
        combo.addItem(h)
    text = f'{current:.1f}'
    idx = combo.findText(text)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    else:
        combo.setCurrentText(text)
    combo.lineEdit().setValidator(QDoubleValidator(0.5, 24.0, 1, combo))
    combo.lineEdit().setPlaceholderText("例: 8.0")
    return combo


def _parse_hours(combo: QComboBox) -> float:
    try:
        v = float(combo.currentText())
        return max(0.5, min(24.0, v))
    except ValueError:
        return 0.0

_STATUS_LIST = [
    ("planned",     "予定"),
    ("in_progress", "進行中"),
    ("completed",   "完了"),
    ("cancelled",   "キャンセル"),
]


class WorkerDialog(QDialog):
    def __init__(self, parent=None, worker=None):
        super().__init__(parent)
        self.setWindowTitle("担当者 " + ("編集" if worker else "追加"))
        self.setMinimumWidth(320)

        layout = QFormLayout(self)
        self.name_edit = QLineEdit(worker["name"] if worker else "")
        self.dept_edit = QLineEdit(worker.get("department", "") if worker else "")
        layout.addRow("氏名 *:", self.name_edit)
        layout.addRow("部署:",   self.dept_edit)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_data(self):
        return {"name": self.name_edit.text().strip(),
                "department": self.dept_edit.text().strip()}

    def accept(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "入力エラー", "氏名を入力してください")
            return
        super().accept()


class TaskDialog(QDialog):
    def __init__(self, parent=None, task=None):
        super().__init__(parent)
        self.setWindowTitle("作業 " + ("編集" if task else "追加"))
        self.setMinimumWidth(360)

        layout = QFormLayout(self)
        self.title_edit = QLineEdit(task["title"] if task else "")
        self.desc_edit  = QLineEdit(task.get("description", "") if task else "")
        self.cat_edit   = QLineEdit(task.get("category", "")    if task else "")
        layout.addRow("作業名 *:", self.title_edit)
        layout.addRow("説明:",     self.desc_edit)
        layout.addRow("カテゴリ:", self.cat_edit)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_data(self):
        return {"title":       self.title_edit.text().strip(),
                "description": self.desc_edit.text().strip(),
                "category":    self.cat_edit.text().strip()}

    def accept(self):
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, "入力エラー", "作業名を入力してください")
            return
        super().accept()


def _fill_combo(combo, items, key_id, key_label, current_id=None):
    combo.clear()
    for item in items:
        combo.addItem(item[key_label], item[key_id])
    if current_id is not None:
        for i in range(combo.count()):
            if combo.itemData(i) == current_id:
                combo.setCurrentIndex(i)
                break


def _make_editable_task_combo(tasks, current_id=None) -> QComboBox:
    """作業名コンボ（プルダウン選択＋直接入力対応）を生成して返す"""
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    _fill_combo(combo, tasks, "id", "title", current_id)
    combo.lineEdit().setPlaceholderText("選択または直接入力…")
    c = combo.completer()
    if c:
        c.setCompletionMode(QCompleter.PopupCompletion)
        c.setFilterMode(Qt.MatchContains)
    return combo


def resolve_task_combo(combo) -> int | None:
    """
    編集可能コンボの現在値から task_id を解決する。
      - 既存作業が選択されていればそのIDを返す
      - 未登録の名前が入力されていれば新規作成してIDを返す
      - 空欄なら None
    """
    typed = combo.currentText().strip()
    if not typed:
        return None

    idx = combo.currentIndex()
    if idx >= 0 and combo.itemData(idx) is not None:
        if combo.itemText(idx) == typed:
            return combo.itemData(idx)

    for t in db.get_all_tasks():
        if t["title"].strip() == typed:
            return t["id"]

    return db.add_task(typed)


class ScheduleDialog(QDialog):
    def __init__(self, parent=None, schedule=None):
        super().__init__(parent)
        self.setWindowTitle("予定 " + ("編集" if schedule else "追加"))
        self.setMinimumWidth(420)
        self._resolved_task_id = None

        workers = db.get_all_workers()
        tasks   = db.get_all_tasks()

        layout = QFormLayout(self)

        self.worker_combo = QComboBox()
        _fill_combo(self.worker_combo, workers, "id", "name",
                    schedule.get("worker_id") if schedule else None)

        self.task_combo = _make_editable_task_combo(
            tasks, schedule.get("task_id") if schedule else None
        )

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(
            QDate.fromString(schedule["scheduled_date"], "yyyy-MM-dd")
            if schedule else QDate.currentDate()
        )

        self.hours_spin = _make_hours_combo(
            schedule.get("scheduled_hours", 8.0) if schedule else 8.0
        )

        self.status_combo = QComboBox()
        for key, label in _STATUS_LIST:
            self.status_combo.addItem(label, key)
        if schedule:
            for i, (key, _) in enumerate(_STATUS_LIST):
                if key == schedule.get("status", "planned"):
                    self.status_combo.setCurrentIndex(i)
                    break

        self.note_edit = QLineEdit(schedule.get("note", "") if schedule else "")

        layout.addRow("担当者 *:",    self.worker_combo)
        layout.addRow("作業名 *:",    self.task_combo)
        layout.addRow("予定日 *:",    self.date_edit)
        layout.addRow("予定時間:",    self.hours_spin)
        layout.addRow("ステータス:", self.status_combo)
        layout.addRow("作業項目:",    self.note_edit)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def accept(self):
        self._resolved_task_id = resolve_task_combo(self.task_combo)
        if not self._resolved_task_id:
            QMessageBox.warning(self, "入力エラー", "作業名を入力してください")
            return
        if _parse_hours(self.hours_spin) <= 0:
            QMessageBox.warning(self, "入力エラー", "予定時間を正しく入力してください")
            return
        super().accept()

    def get_data(self):
        return {
            "worker_id":       self.worker_combo.currentData(),
            "task_id":         self._resolved_task_id,
            "scheduled_date":  self.date_edit.date().toString("yyyy-MM-dd"),
            "scheduled_hours": _parse_hours(self.hours_spin),
            "status":          self.status_combo.currentData(),
            "note":            self.note_edit.text().strip(),
        }


class ActualDialog(QDialog):
    def __init__(self, parent=None, actual=None, schedule=None):
        super().__init__(parent)
        self.setWindowTitle("実績 " + ("編集" if actual else "追加"))
        self.setMinimumWidth(420)
        self._resolved_task_id = None

        workers = db.get_all_workers()
        tasks   = db.get_all_tasks()

        src = actual or schedule
        layout = QFormLayout(self)

        self.worker_combo = QComboBox()
        _fill_combo(self.worker_combo, workers, "id", "name",
                    src.get("worker_id") if src else None)

        self.task_combo = _make_editable_task_combo(
            tasks, src.get("task_id") if src else None
        )

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        _adate = (actual or {}).get("actual_date") or (schedule or {}).get("actual_date")
        if _adate:
            self.date_edit.setDate(QDate.fromString(_adate, "yyyy-MM-dd"))
        else:
            self.date_edit.setDate(QDate.currentDate())

        self.hours_spin = _make_hours_combo(
            actual.get("actual_hours", 8.0) if actual else 8.0
        )

        self.note_edit = QLineEdit(
            actual.get("note", "") if actual else (schedule or {}).get("note", "")
        )

        layout.addRow("担当者 *:", self.worker_combo)
        layout.addRow("作業名 *:", self.task_combo)
        layout.addRow("実績日 *:", self.date_edit)
        layout.addRow("実績時間:", self.hours_spin)
        layout.addRow("実施内容:", self.note_edit)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def accept(self):
        self._resolved_task_id = resolve_task_combo(self.task_combo)
        if not self._resolved_task_id:
            QMessageBox.warning(self, "入力エラー", "作業名を入力してください")
            return
        super().accept()

    def get_data(self):
        return {
            "worker_id":    self.worker_combo.currentData(),
            "task_id":      self._resolved_task_id,
            "actual_date":  self.date_edit.date().toString("yyyy-MM-dd"),
            "actual_hours": _parse_hours(self.hours_spin),
            "note":         self.note_edit.text().strip(),
        }


from holidays import get_holiday as _get_holiday_func


class _MultiSelectCalendar(QCalendarWidget):
    """クリックで日付を選択/解除、Shift+クリックで範囲選択するカレンダー。"""

    datesChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected = set()   # set of date objects
        self._anchor   = None    # last single-click date (range 選択の起点)
        # SingleSelection にすることで clicked シグナルが確実に発火する
        self.setSelectionMode(QCalendarWidget.SingleSelection)
        self.clicked.connect(self._on_clicked)
        # ナビゲーションバーのスタイルは main.py のグローバルスタイルシートで管理

    @staticmethod
    def _get_holiday(d: date) -> str:
        return _get_holiday_func(d)

    def _on_clicked(self, qdate):
        d    = date(qdate.year(), qdate.month(), qdate.day())
        mods = QApplication.keyboardModifiers()
        if (mods & Qt.ShiftModifier) and self._anchor:
            # Shift+クリック → アンカーから d まで範囲選択
            d0, d1 = min(d, self._anchor), max(d, self._anchor)
            cur = d0
            while cur <= d1:
                self._selected.add(cur)
                cur += timedelta(days=1)
        else:
            # 通常クリック → トグル
            if d in self._selected:
                self._selected.discard(d)
            else:
                self._selected.add(d)
            self._anchor = d
        self.updateCells()
        self.datesChanged.emit()

    def paintCell(self, painter, rect, qdate):
        d       = date(qdate.year(), qdate.month(), qdate.day())
        holiday = self._get_holiday(d)

        painter.save()

        if d in self._selected:
            # 選択済み → 青背景・白文字
            painter.fillRect(rect.adjusted(1, 1, -1, -1), QColor('#1976D2'))
            f = QFont("Yu Gothic UI"); f.setPointSize(9); f.setBold(True)
            painter.setFont(f)
            painter.setPen(QColor('#FFFFFF'))
            painter.drawText(rect, Qt.AlignCenter, str(qdate.day()))
        elif holiday:
            # 祝日 → 薄赤背景・赤文字 + 祝日名（小フォント）
            painter.fillRect(rect.adjusted(1, 1, -1, -1), QColor('#FFCDD2'))
            f = QFont("Yu Gothic UI"); f.setPointSize(9); f.setBold(True)
            painter.setFont(f)
            painter.setPen(QColor('#C62828'))
            day_rect = QRect(rect.x(), rect.y(),
                             rect.width(), rect.height() * 6 // 10)
            painter.drawText(day_rect, Qt.AlignCenter, str(qdate.day()))
            f2 = QFont("Yu Gothic UI"); f2.setPointSize(5)
            painter.setFont(f2)
            name_rect = QRect(rect.x(), rect.y() + rect.height() * 6 // 10,
                              rect.width(), rect.height() * 4 // 10)
            painter.drawText(name_rect, Qt.AlignCenter, holiday)
        else:
            super().paintCell(painter, rect, qdate)

        painter.restore()

    def get_dates(self):
        return sorted(self._selected)

    def add_dates(self, dates):
        for d in dates:
            self._selected.add(d)
        self.updateCells()
        self.datesChanged.emit()

    def set_dates(self, dates):
        self._selected = set(dates)
        self.updateCells()
        self.datesChanged.emit()

    def clear_selection(self):
        self._selected.clear()
        self.updateCells()
        self.datesChanged.emit()


class _WeeklyAddDialog(QDialog):
    """毎週単位で日付をカレンダーに追加するサブダイアログ。"""

    def __init__(self, parent=None, start_date=None, end_date=None):
        super().__init__(parent)
        self.setWindowTitle("毎週単位で追加")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ── 繰り返し期間 ──────────────────────────────────────────────────
        period_box = QGroupBox("繰り返し期間　（初期設定：6ヶ月）")
        pr = QHBoxLayout(period_box)
        today_q = QDate.currentDate()
        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDate(
            QDate.fromString(start_date, "yyyy-MM-dd") if start_date else today_q
        )
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDate(self.from_date.date().addMonths(6))
        pr.addWidget(QLabel("開始:"))
        pr.addWidget(self.from_date)
        pr.addWidget(QLabel("〜  終了:"))
        pr.addWidget(self.to_date)
        layout.addWidget(period_box)

        # ── 毎週繰り返す曜日 ─────────────────────────────────────────────
        wd_box  = QGroupBox("毎週繰り返す曜日")
        wd_vl   = QVBoxLayout(wd_box)

        wd_row = QHBoxLayout()
        self.wd_cbs = []
        for i, lbl in enumerate(['月', '火', '水', '木', '金', '土', '日']):
            cb = QCheckBox(lbl)
            cb.setChecked(i < 5)   # 平日デフォルトON
            cb.stateChanged.connect(self._update_preview)
            self.wd_cbs.append(cb)
            wd_row.addWidget(cb)
        wd_vl.addLayout(wd_row)

        # 一括選択ボタン
        qsel_row = QHBoxLayout()
        for label, days in [("平日のみ", range(5)), ("毎日", range(7)), ("土日のみ", (5, 6)), ("クリア", ())]:
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            _days = list(days)
            btn.clicked.connect(lambda _, d=_days: self._quick_select(d))
            qsel_row.addWidget(btn)
        qsel_row.addStretch()
        wd_vl.addLayout(qsel_row)
        layout.addWidget(wd_box)

        # ── 日数プレビュー ────────────────────────────────────────────────
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("font-weight: bold; color: #1565C0; padding: 4px;")
        layout.addWidget(self.preview_label)

        # ── ボタン ────────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # シグナル接続
        self.from_date.dateChanged.connect(self._update_preview)
        self.to_date.dateChanged.connect(self._update_preview)
        self._update_preview()

    def _quick_select(self, days: list):
        for i, cb in enumerate(self.wd_cbs):
            cb.setChecked(i in days)

    def _update_preview(self):
        n = len(self.get_dates())
        checked = [cb.text() for cb in self.wd_cbs if cb.isChecked()]
        days_str = "・".join(checked) if checked else "（曜日未選択）"
        self.preview_label.setText(f"毎週  {days_str}  →  {n} 日間 追加されます")

    def get_dates(self) -> list:
        qf, qt = self.from_date.date(), self.to_date.date()
        d0 = date(qf.year(), qf.month(), qf.day())
        d1 = date(qt.year(), qt.month(), qt.day())
        target = {i for i, cb in enumerate(self.wd_cbs) if cb.isChecked()}
        dates, cur = [], d0
        while cur <= d1:
            if cur.weekday() in target:
                dates.append(cur)
            cur += timedelta(days=1)
        return dates


class _MonthlyAddDialog(QDialog):
    """毎月単位で日付をカレンダーに追加するサブダイアログ。
    ・日にち指定: 毎月 N日
    ・曜日指定:   毎月 第N曜日 / 最終曜日
    両方を同時に指定可（和集合）。
    """

    _WEEK_LABELS = ['第1', '第2', '第3', '第4', '最終']
    _WD_LABELS   = ['月', '火', '水', '木', '金', '土', '日']

    def __init__(self, parent=None, start_date=None):
        super().__init__(parent)
        self.setWindowTitle("毎月単位で追加")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ── 繰り返し期間 ──────────────────────────────────────────────────
        period_box = QGroupBox("繰り返し期間　（初期設定：6ヶ月）")
        pr = QHBoxLayout(period_box)
        today_q = QDate.currentDate()
        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDate(
            QDate.fromString(start_date, "yyyy-MM-dd") if start_date else today_q
        )
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDate(self.from_date.date().addMonths(6))
        pr.addWidget(QLabel("開始:"))
        pr.addWidget(self.from_date)
        pr.addWidget(QLabel("〜  終了:"))
        pr.addWidget(self.to_date)
        layout.addWidget(period_box)

        # ── 毎月の日にち指定 ──────────────────────────────────────────────
        dom_box  = QGroupBox("毎月の日にち指定（複数選択可）")
        dom_grid = QGridLayout(dom_box)
        dom_grid.setSpacing(2)
        dom_grid.setContentsMargins(6, 6, 6, 6)
        self.dom_cbs = []
        for i in range(31):
            cb = QCheckBox(str(i + 1))
            cb.setFixedWidth(40)
            cb.stateChanged.connect(self._update_preview)
            self.dom_cbs.append(cb)
            dom_grid.addWidget(cb, i // 7, i % 7)
        layout.addWidget(dom_box)

        # ── 毎月の第N曜日指定 ─────────────────────────────────────────────
        nth_box  = QGroupBox("毎月の曜日指定（第N曜日・複数選択可）")
        nth_grid = QGridLayout(nth_box)
        nth_grid.setSpacing(4)
        nth_grid.setContentsMargins(6, 10, 6, 6)

        # ヘッダー（曜日名）
        nth_grid.addWidget(QLabel(""), 0, 0)
        for wd, lbl in enumerate(self._WD_LABELS):
            hdr = QLabel(lbl)
            hdr.setAlignment(Qt.AlignCenter)
            nth_grid.addWidget(hdr, 0, wd + 1)

        # 行：第1〜第4・最終
        self.nth_cbs: list = []
        for wi, wlbl in enumerate(self._WEEK_LABELS):
            row_lbl = QLabel(wlbl)
            row_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            nth_grid.addWidget(row_lbl, wi + 1, 0)
            row_cbs = []
            for wd in range(7):
                cb = QCheckBox()
                cb.setFixedWidth(28)
                cb.stateChanged.connect(self._update_preview)
                nth_grid.addWidget(cb, wi + 1, wd + 1, Qt.AlignCenter)
                row_cbs.append(cb)
            self.nth_cbs.append(row_cbs)

        layout.addWidget(nth_box)

        # ── 日数プレビュー ────────────────────────────────────────────────
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("font-weight: bold; color: #1565C0; padding: 4px;")
        layout.addWidget(self.preview_label)

        # ── ボタン ────────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # シグナル接続
        self.from_date.dateChanged.connect(self._update_preview)
        self.to_date.dateChanged.connect(self._update_preview)
        self._update_preview()

    def _update_preview(self):
        n = len(self.get_dates())
        self.preview_label.setText(f"毎月繰り返し  →  {n} 日間 追加されます")

    def get_dates(self) -> list:
        import calendar as _cal
        qf, qt = self.from_date.date(), self.to_date.date()
        d0 = date(qf.year(), qf.month(), qf.day())
        d1 = date(qt.year(), qt.month(), qt.day())

        # 日にち指定セット
        dom_target = {i + 1 for i, cb in enumerate(self.dom_cbs) if cb.isChecked()}

        # 第N曜日指定セット: (week_idx, weekday)  week_idx 0-3=第1-4, 4=最終
        nth_target: set = set()
        for wi, row in enumerate(self.nth_cbs):
            for wd, cb in enumerate(row):
                if cb.isChecked():
                    nth_target.add((wi, wd))

        result: set = set()
        cur = d0
        while cur <= d1:
            # 日にち指定
            if cur.day in dom_target:
                result.add(cur)
            # 第N曜日指定
            if nth_target:
                wd       = cur.weekday()       # 0=月 … 6=日
                week_num = (cur.day - 1) // 7  # 0=第1 … 3=第4
                if (week_num, wd) in nth_target:
                    result.add(cur)
                # 最終曜日
                if (4, wd) in nth_target:
                    _, last_day = _cal.monthrange(cur.year, cur.month)
                    if last_day - cur.day < 7:
                        result.add(cur)
            cur += timedelta(days=1)

        return sorted(result)


class GanttScheduleDialog(QDialog):
    """カレンダー複数日選択＋繰り返し指定に対応した予定ダイアログ。"""

    def __init__(self, parent=None, worker=None, task=None,
                 start_date=None, end_date=None,
                 initial_dates=None,
                 hours_per_day=8.0, status="planned", note="", is_edit=False):
        super().__init__(parent)
        self._worker     = worker
        self._task       = task
        self._start_date = start_date
        self._end_date   = end_date
        self.setWindowTitle("予定 " + ("編集" if is_edit else "追加"))
        self.setMinimumSize(640, 440)

        outer = QVBoxLayout(self)

        # ── 担当者・作業名 ────────────────────────────────────────────────
        info = QHBoxLayout()
        info.addWidget(QLabel(f"<b>担当者:</b> {worker['name'] if worker else ''}"))
        info.addSpacing(24)
        info.addWidget(QLabel(f"<b>作業名:</b> {task['title'] if task else ''}"))
        info.addStretch()
        outer.addLayout(info)

        # ── メイン行（カレンダー ＋ 設定パネル）──────────────────────────
        mid = QHBoxLayout()

        # カレンダー（左）
        cal_box = QGroupBox(
            "日付選択  ─  クリック: 選択/解除　　Shift+クリック: 範囲選択"
        )
        cal_vl = QVBoxLayout(cal_box)
        self.calendar = _MultiSelectCalendar()
        if start_date:
            qd = QDate.fromString(start_date, "yyyy-MM-dd")
            self.calendar.setCurrentPage(qd.year(), qd.month())
        cal_vl.addWidget(self.calendar)

        # カレンダー操作ボタン行
        cal_btn_row = QHBoxLayout()
        clr_btn = QPushButton("選択をクリア")
        clr_btn.clicked.connect(self.calendar.clear_selection)
        cal_btn_row.addWidget(clr_btn)

        wk_btn = QPushButton("毎週単位で追加")
        wk_btn.clicked.connect(self._open_weekly_dialog)
        cal_btn_row.addWidget(wk_btn)

        mo_btn = QPushButton("毎月単位で追加")
        mo_btn.clicked.connect(self._open_monthly_dialog)
        cal_btn_row.addWidget(mo_btn)

        cal_vl.addLayout(cal_btn_row)
        mid.addWidget(cal_box, 3)

        # 設定パネル（右）
        panel = QVBoxLayout()

        opt_box = QGroupBox("設定")
        opt_fl  = QFormLayout(opt_box)

        self.skip_we      = QCheckBox("土日を除く")
        self.hours_spin   = _make_hours_combo(hours_per_day)
        self.status_combo = QComboBox()
        for key, lbl in _STATUS_LIST:
            self.status_combo.addItem(lbl, key)
        for i, (key, _) in enumerate(_STATUS_LIST):
            if key == status:
                self.status_combo.setCurrentIndex(i)
                break
        self.note_edit   = QLineEdit(note)
        self.count_label = QLabel()

        opt_fl.addRow("土日を除く:", self.skip_we)
        opt_fl.addRow("時間/日:",    self.hours_spin)
        opt_fl.addRow("ステータス:", self.status_combo)
        opt_fl.addRow("作業項目:",   self.note_edit)
        opt_fl.addRow("対象日数:",   self.count_label)
        panel.addWidget(opt_box)
        panel.addStretch()

        mid.addLayout(panel, 2)
        outer.addLayout(mid)

        # ── ボタン ───────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

        # シグナル接続
        self.calendar.datesChanged.connect(self._update_count)
        self.skip_we.stateChanged.connect(self._update_count)

        # 初期日付をカレンダーに反映
        if initial_dates:
            d = initial_dates[0]
            self.calendar.setCurrentPage(d.year, d.month)
            self.calendar.set_dates(initial_dates)
        elif start_date:
            d0 = date.fromisoformat(start_date)
            d1 = date.fromisoformat(end_date) if end_date else d0
            cur, init = d0, []
            while cur <= d1:
                init.append(cur)
                cur += timedelta(days=1)
            self.calendar.set_dates(init)
        else:
            self._update_count()

    # ── 週・月単位追加サブダイアログを開く ───────────────────────────────

    def _open_weekly_dialog(self):
        dlg = _WeeklyAddDialog(
            self, start_date=self._start_date, end_date=self._end_date
        )
        if dlg.exec_() == QDialog.Accepted:
            self.calendar.add_dates(dlg.get_dates())

    def _open_monthly_dialog(self):
        dlg = _MonthlyAddDialog(self, start_date=self._start_date)
        if dlg.exec_() == QDialog.Accepted:
            self.calendar.add_dates(dlg.get_dates())

    # ── helpers ───────────────────────────────────────────────────────────────

    def get_target_dates(self):
        skip = self.skip_we.isChecked()
        return [d for d in self.calendar.get_dates()
                if not skip or d.weekday() < 5]

    def _update_count(self):
        self.count_label.setText(f"<b>{len(self.get_target_dates())}</b> 日間")

    def get_schedules(self):
        hours  = _parse_hours(self.hours_spin)
        status = self.status_combo.currentData()
        note   = self.note_edit.text().strip()
        return [
            {
                "worker_id":       self._worker["id"],
                "task_id":         self._task["id"],
                "scheduled_date":  d.strftime("%Y-%m-%d"),
                "scheduled_hours": hours,
                "status":          status,
                "note":            note,
            }
            for d in self.get_target_dates()
        ]

    def accept(self):
        if not self.get_target_dates():
            QMessageBox.warning(self, "入力エラー", "日付を選択してください")
            return
        if _parse_hours(self.hours_spin) <= 0:
            QMessageBox.warning(self, "入力エラー", "時間を正しく入力してください")
            return
        super().accept()
