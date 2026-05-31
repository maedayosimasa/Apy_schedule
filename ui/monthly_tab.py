"""
月次スプレッドシートタブ

  表示:
    1か月分の日付を列に展開したスプレッドシート形式
    担当者×作業ごとに「予定行」と「実績行」の2行で表示

  編集:
    日付セルをダブルクリック or キー入力で時間を直接編集
    Enter / Tab / フォーカス移動で即座にDBへ自動保存
    空欄・0で入力すると該当レコードを削除
"""
import calendar
from datetime import date
from itertools import groupby

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QHeaderView, QStyledItemDelegate, QLineEdit,
    QDialog, QFormLayout, QDialogButtonBox, QMessageBox,
)
from PyQt5.QtCore import Qt, QSize, QTimer, QEvent
from PyQt5.QtGui import QColor, QPen, QFont, QDoubleValidator, QFontMetrics
from ui.zoom_mixin import ZoomMixin, ZoomableTableWidget

import database as db
from holidays import get_holiday
from ui.dialogs import _make_editable_task_combo, resolve_task_combo

# ── 定数 ─────────────────────────────────────────────────────────────────────
_WD       = ['月', '火', '水', '木', '金', '土', '日']
_T_SCHED  = 'schedule'
_T_ACTUAL = 'actual'

_C_SCHED_FILL  = '#BBDEFB'   # 予定バー背景
_C_ACTUAL_FILL = '#C8E6C9'   # 実績バー背景
_C_SCHED_TEXT  = '#0D47A1'
_C_ACTUAL_TEXT = '#1B5E20'
_C_WEEKEND     = '#F0F0F0'
_C_TODAY_BG    = '#FFFDE7'
_C_TODAY_HDR   = '#E65100'


def _fmt(h: float) -> str:
    """8.0→'8'  7.5→'7.5'  0.0→''"""
    if h <= 0:
        return ''
    return str(int(h)) if h == int(h) else f'{h:.1f}'


# ── delegate ─────────────────────────────────────────────────────────────────

class _MonthDelegate(QStyledItemDelegate):

    def paint(self, painter, option, index):
        d = index.data(Qt.UserRole)
        if not isinstance(d, dict) or d.get('type') not in (_T_SCHED, _T_ACTUAL):
            super().paint(painter, option, index)
            return

        painter.save()
        rect = option.rect

        # 背景（優先度: 今日 > 祝日 > 土日 > 通常、ペア交互色）
        is_odd_pair = (index.row() // 2) % 2 == 1
        if d.get('is_today'):
            bg = QColor(_C_TODAY_BG)
        elif d.get('holiday'):
            bg = QColor('#FFD9DC') if is_odd_pair else QColor('#FFEBEE')
        elif d.get('is_weekend'):
            bg = QColor('#E6EEF3') if is_odd_pair else QColor(_C_WEEKEND)
        else:
            bg = QColor('#E8F4FD') if is_odd_pair else QColor('#FFFFFF')
        painter.fillRect(rect, bg)

        # 値セル
        h = d.get('hours', 0)
        if h > 0:
            fill  = QColor(_C_SCHED_FILL  if d['type'] == _T_SCHED else _C_ACTUAL_FILL)
            tc    = QColor(_C_SCHED_TEXT  if d['type'] == _T_SCHED else _C_ACTUAL_TEXT)
            painter.fillRect(rect.adjusted(1, 1, -1, -1), fill)
            f = QFont("Yu Gothic UI"); f.setPointSize(8); painter.setFont(f)
            painter.setPen(tc)
            painter.drawText(rect, Qt.AlignCenter, _fmt(h))

        # 選択
        if option.state & 0x0002:
            painter.fillRect(rect, QColor(25, 118, 210, 45))

        # グリッド線
        painter.setPen(QPen(QColor('#E0E0E0'), 1))
        painter.drawLine(rect.right(), rect.top(),    rect.right(), rect.bottom())
        painter.drawLine(rect.left(),  rect.bottom(), rect.right(), rect.bottom())

        painter.restore()

    def createEditor(self, parent, option, index):
        d = index.data(Qt.UserRole)
        if not isinstance(d, dict) or d.get('type') not in (_T_SCHED, _T_ACTUAL):
            return None
        ed = QLineEdit(parent)
        ed.setValidator(QDoubleValidator(0.0, 24.0, 2, ed))
        ed.setAlignment(Qt.AlignCenter)
        return ed

    def setEditorData(self, editor, index):
        d = index.data(Qt.UserRole)
        h = d.get('hours', 0) if isinstance(d, dict) else 0
        editor.setText(str(h) if h > 0 else '')
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.text(), Qt.EditRole)

    def sizeHint(self, option, index):
        return QSize(42, 26)


# ── main tab ─────────────────────────────────────────────────────────────────

class MonthlyTab(QWidget, ZoomMixin):
    N_FIXED = 3   # 担当者 | 作業名 | 種別

    def __init__(self):
        super().__init__()
        self._init_zoom("zoom_monthly")
        today = date.today()
        self._year          = today.year
        self._month         = today.month
        self._dates: list   = []
        self._row_meta: list= []   # [{type, worker, task}]
        self._sched_lu: dict  = {}
        self._actual_lu: dict = {}
        self._loading        = False
        self._pinned_pairs: set = set()
        self._cur_n_date_cols: int = 0
        self._cur_n_cols:      int = 0
        self._setup_ui()
        QTimer.singleShot(0, self.refresh)

    # ── setup ─────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # ── ナビゲーション行 ────────────────────────────────────────────────
        nav = QHBoxLayout()

        prev_btn = QPushButton("◀ 前月")
        prev_btn.setFixedWidth(68)
        prev_btn.clicked.connect(self._prev_month)
        nav.addWidget(prev_btn)

        self.month_label = QLabel()
        self.month_label.setAlignment(Qt.AlignCenter)
        self.month_label.setMinimumWidth(140)
        self.month_label.setStyleSheet("font-size:15px; font-weight:bold;")
        nav.addWidget(self.month_label)

        next_btn = QPushButton("次月 ▶")
        next_btn.setFixedWidth(68)
        next_btn.clicked.connect(self._next_month)
        nav.addWidget(next_btn)

        today_btn = QPushButton("今月")
        today_btn.setFixedWidth(52)
        today_btn.clicked.connect(self._goto_today)
        nav.addWidget(today_btn)

        nav.addSpacing(16)
        nav.addWidget(QLabel("担当者:"))
        self.worker_filter = QComboBox()
        self.worker_filter.setMinimumWidth(110)
        nav.addWidget(self.worker_filter)

        refresh_btn = QPushButton("更新")
        refresh_btn.setFixedWidth(46)
        refresh_btn.clicked.connect(self.refresh)
        nav.addWidget(refresh_btn)

        add_row_btn = QPushButton("+ 行を追加")
        add_row_btn.setFixedWidth(90)
        add_row_btn.clicked.connect(self._add_row_dialog)
        nav.addWidget(add_row_btn)

        self._make_zoom_controls(nav)
        nav.addStretch()
        layout.addLayout(nav)

        # ── 凡例 ──────────────────────────────────────────────────────────────
        ll = QHBoxLayout()
        for color, text_c, label in [
            (_C_SCHED_FILL,  _C_SCHED_TEXT,  '予定時間'),
            (_C_ACTUAL_FILL, _C_ACTUAL_TEXT, '実績時間'),
        ]:
            lbl = QLabel(f"■ {label}")
            lbl.setStyleSheet(
                f"color:{text_c}; background:{color}; padding:2px 8px;"
                f" border:1px solid #888; border-radius:3px; font-size:11px;"
            )
            ll.addWidget(lbl)
        ll.addWidget(QLabel("  ダブルクリックまたはキー入力で直接編集  /  0か空白で削除"))
        ll.addStretch()
        layout.addLayout(ll)

        # ── テーブル ───────────────────────────────────────────────────────────
        self.table = ZoomableTableWidget()
        self.table.setItemDelegate(_MonthDelegate())
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.AnyKeyPressed
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.horizontalHeader().setMinimumSectionSize(16)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table)
        self._register_zoom_table(self.table)

    # ── 月ナビ ────────────────────────────────────────────────────────────────

    def _prev_month(self):
        if self._month == 1: self._year -= 1; self._month = 12
        else:                self._month -= 1
        self.refresh()

    def _next_month(self):
        if self._month == 12: self._year += 1; self._month = 1
        else:                 self._month += 1
        self.refresh()

    def _goto_today(self):
        today = date.today()
        self._year, self._month = today.year, today.month
        self.refresh()

    # ── public ────────────────────────────────────────────────────────────────

    def refresh(self):
        self._reload_worker_filter()
        self._build_table()

    # ── zoom ─────────────────────────────────────────────────────────────────

    def _apply_col_widths(self) -> None:
        if self._cur_n_cols == 0:
            return
        fm   = self.table.fontMetrics()
        _pad = 12
        self.table.setColumnWidth(0, fm.horizontalAdvance("山田 太郎") + _pad * 2)
        self.table.setColumnWidth(1, fm.horizontalAdvance("作業名テストABCDE") + _pad * 2)
        self.table.setColumnWidth(2, fm.horizontalAdvance("予実") + _pad)
        _dw = fm.horizontalAdvance("88") + _pad
        for c in range(self.N_FIXED, self.N_FIXED + self._cur_n_date_cols):
            self.table.setColumnWidth(c, _dw)
        self.table.setColumnWidth(self._cur_n_cols - 1, fm.horizontalAdvance("999.9") + _pad)

    def _apply_zoom(self) -> None:
        font = self._zoom_font()
        self.table.setFont(font)
        fm = QFontMetrics(font)
        self.table.verticalHeader().setDefaultSectionSize(fm.height() + 10)
        self._apply_col_widths()
        self._update_zoom_label()

    # ── テーブル構築 ──────────────────────────────────────────────────────────

    def _reload_worker_filter(self):
        current = self.worker_filter.currentData()
        self.worker_filter.clear()
        self.worker_filter.addItem("全員", None)
        for w in db.get_all_workers():
            self.worker_filter.addItem(w["name"], w["id"])
        if current is not None:
            for i in range(self.worker_filter.count()):
                if self.worker_filter.itemData(i) == current:
                    self.worker_filter.setCurrentIndex(i)
                    break

    def _get_month_dates(self):
        _, n_days = calendar.monthrange(self._year, self._month)
        return [date(self._year, self._month, d) for d in range(1, n_days + 1)]

    def _build_table(self):
        self._loading = True
        today         = date.today()
        self._dates   = self._get_month_dates()
        self.month_label.setText(f"{self._year}年  {self._month}月")

        d_from = self._dates[0].strftime('%Y-%m-%d')
        d_to   = self._dates[-1].strftime('%Y-%m-%d')
        wf     = self.worker_filter.currentData()

        # DB 取得
        sched_list  = db.get_schedules(worker_id=wf, date_from=d_from, date_to=d_to)
        actual_list = db.get_actuals(worker_id=wf, date_from=d_from, date_to=d_to)

        self._sched_lu  = {(s['worker_id'], s['task_id'], s['scheduled_date']): s
                           for s in sched_list}
        self._actual_lu = {(a['worker_id'], a['task_id'], a['actual_date']): a
                           for a in actual_list}

        # 表示ペア収集
        pairs: set = set()
        for s in sched_list:  pairs.add((s['worker_id'], s['task_id']))
        for a in actual_list: pairs.add((a['worker_id'], a['task_id']))
        pairs |= self._pinned_pairs
        if wf:
            pairs = {(w, t) for w, t in pairs if w == wf}

        all_workers = db.get_all_workers()
        if wf:
            all_workers = [w for w in all_workers if w['id'] == wf]
        w_map = {w['id']: w for w in all_workers}
        t_map = {t['id']: t for t in db.get_all_tasks()}

        pair_rows = []
        for w in all_workers:
            for wid, tid in sorted(pairs,
                                   key=lambda x: t_map.get(x[1], {}).get('title', '')):
                if wid == w['id'] and wid in w_map and tid in t_map:
                    pair_rows.append({'worker': w_map[wid], 'task': t_map[tid]})

        # ── テーブル寸法 ──────────────────────────────────────────────────────
        n_date_cols = len(self._dates)
        n_cols      = self.N_FIXED + n_date_cols + 1   # +1 = 月計
        n_rows      = len(pair_rows) * 2               # 予定行 + 実績行

        self.table.clearSpans()
        self.table.setRowCount(n_rows)
        self.table.setColumnCount(n_cols)

        # ヘッダーラベル
        date_hdrs = [
            f"{d.day}\n({_WD[d.weekday()]})"
            for d in self._dates
        ]
        self.table.setHorizontalHeaderLabels(
            ['担当者', '作業名', '種別'] + date_hdrs + ['月計']
        )

        # 列幅（フォントメトリクスから算出）
        self._cur_n_date_cols = n_date_cols
        self._cur_n_cols      = n_cols
        self.table.setFont(self._zoom_font())
        self._apply_col_widths()

        # 土日・祝日・今日ヘッダー色
        for ci, d in enumerate(self._dates):
            h = self.table.horizontalHeaderItem(self.N_FIXED + ci)
            if h is None:
                h = QTableWidgetItem()
                self.table.setHorizontalHeaderItem(self.N_FIXED + ci, h)
            holiday = get_holiday(d)
            if d == today:
                h.setBackground(QColor(_C_TODAY_HDR))
                h.setForeground(QColor('white'))
                f = h.font(); f.setBold(True); h.setFont(f)
                if holiday:
                    h.setToolTip(holiday)
            elif holiday:
                h.setBackground(QColor('#FFCDD2'))
                h.setForeground(QColor('#C62828'))
                f = h.font(); f.setBold(True); h.setFont(f)
                h.setToolTip(holiday)
            elif d.weekday() >= 5:
                h.setBackground(QColor('#BDBDBD'))
                h.setToolTip('')
            else:
                h.setBackground(QColor('#E3F2FD'))
                h.setToolTip('')

        # ── 担当者スパン ──────────────────────────────────────────────────────
        self._row_meta = []
        for pair in pair_rows:
            self._row_meta.append({'type': _T_SCHED,  'worker': pair['worker'], 'task': pair['task']})
            self._row_meta.append({'type': _T_ACTUAL, 'worker': pair['worker'], 'task': pair['task']})

        for wid, grp in groupby(range(len(pair_rows)),
                                key=lambda i: pair_rows[i]['worker']['id']):
            idxs      = list(grp)
            row_start = idxs[0] * 2
            row_span  = len(idxs) * 2
            if row_span > 1:
                self.table.setSpan(row_start, 0, row_span, 1)
            it = QTableWidgetItem(pair_rows[idxs[0]]['worker']['name'])
            it.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            it.setBackground(QColor('#E3F2FD'))
            f = it.font(); f.setBold(True); it.setFont(f)
            self.table.setItem(row_start, 0, it)

        # ── 各ペアのセル埋め ──────────────────────────────────────────────────
        tot_col = n_cols - 1

        for pi, pair in enumerate(pair_rows):
            sr = pi * 2       # 予定行
            ar = pi * 2 + 1   # 実績行
            worker = pair['worker']
            task   = pair['task']

            self.table.setRowHeight(sr, 24)
            self.table.setRowHeight(ar, 24)

            # 作業名（2行スパン）
            self.table.setSpan(sr, 1, 2, 1)
            ti = QTableWidgetItem(task['title'])
            ti.setFlags(ti.flags() & ~Qt.ItemIsEditable)
            ti.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            if pi % 2 == 1:
                ti.setBackground(QColor('#E8F4FD'))
            self.table.setItem(sr, 1, ti)

            # 種別ラベル
            for row, label, bg in [
                (sr, '予定', '#DDEEFF'),
                (ar, '実績', '#DDFFDD'),
            ]:
                ki = QTableWidgetItem(label)
                ki.setFlags(ki.flags() & ~Qt.ItemIsEditable)
                ki.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                ki.setBackground(QColor(bg))
                self.table.setItem(row, 2, ki)

            # 日付セル
            s_total = 0.0
            a_total = 0.0

            for ci, d in enumerate(self._dates):
                ds        = d.strftime('%Y-%m-%d')
                is_we     = d.weekday() >= 5
                is_today  = (d == today)
                col       = self.N_FIXED + ci

                sched   = self._sched_lu.get((worker['id'], task['id'], ds))
                actual  = self._actual_lu.get((worker['id'], task['id'], ds))
                holiday = get_holiday(d)

                sh = (sched  or {}).get('scheduled_hours', 0.0)
                ah = (actual or {}).get('actual_hours',    0.0)
                s_total += sh
                a_total += ah

                # 予定セル
                si = QTableWidgetItem(_fmt(sh))
                si.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                si.setData(Qt.UserRole, {
                    'type': _T_SCHED, 'worker': worker, 'task': task,
                    'date': ds, 'hours': sh, 'existing': sched,
                    'is_weekend': is_we, 'is_today': is_today, 'holiday': holiday,
                })
                if holiday:
                    si.setToolTip(holiday)
                self.table.setItem(sr, col, si)

                # 実績セル
                ai = QTableWidgetItem(_fmt(ah))
                ai.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                ai.setData(Qt.UserRole, {
                    'type': _T_ACTUAL, 'worker': worker, 'task': task,
                    'date': ds, 'hours': ah, 'existing': actual,
                    'is_weekend': is_we, 'is_today': is_today, 'holiday': holiday,
                })
                if holiday:
                    ai.setToolTip(holiday)
                self.table.setItem(ar, col, ai)

            # 月計セル（予定・実績）
            for row, total, bg in [
                (sr, s_total, '#DDEEFF'),
                (ar, a_total, '#DDFFDD'),
            ]:
                tot_it = QTableWidgetItem(_fmt(total))
                tot_it.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                tot_it.setFlags(tot_it.flags() & ~Qt.ItemIsEditable)
                tot_it.setBackground(QColor(bg))
                f2 = tot_it.font(); f2.setBold(True); tot_it.setFont(f2)
                self.table.setItem(row, tot_col, tot_it)

        self._loading = False

    # ── セル編集ハンドラ ──────────────────────────────────────────────────────

    def _on_cell_changed(self, row: int, col: int):
        if self._loading:
            return
        n_cols  = self.table.columnCount()
        tot_col = n_cols - 1
        if col < self.N_FIXED or col == tot_col:
            return

        item = self.table.item(row, col)
        if not item:
            return
        meta = item.data(Qt.UserRole)
        if not isinstance(meta, dict) or meta.get('type') not in (_T_SCHED, _T_ACTUAL):
            return

        # テキストを時間数（float）に変換
        text = item.text().strip()
        try:
            hours = float(text) if text else 0.0
        except ValueError:
            self._loading = True
            item.setText(_fmt(meta.get('hours', 0)))
            self._loading = False
            return
        hours = max(0.0, min(24.0, hours))

        worker   = meta['worker']
        task     = meta['task']
        date_str = meta['date']
        existing = meta.get('existing')
        rtype    = meta['type']

        # ── DB 保存 ───────────────────────────────────────────────────────────
        if rtype == _T_SCHED:
            if hours > 0:
                if existing:
                    db.update_schedule(
                        existing['id'], worker['id'], task['id'], date_str,
                        hours,
                        existing.get('status', 'planned'),
                        existing.get('note',   ''),
                    )
                    existing['scheduled_hours'] = hours
                else:
                    new_id   = db.add_schedule(worker['id'], task['id'], date_str, hours)
                    existing = db.get_schedule_by_id(new_id)
                    self._sched_lu[(worker['id'], task['id'], date_str)] = existing
            else:
                if existing:
                    db.delete_schedule(existing['id'])
                    self._sched_lu.pop((worker['id'], task['id'], date_str), None)
                    existing = None
        else:  # actual
            if hours > 0:
                if existing:
                    db.update_actual(
                        existing['id'], worker['id'], task['id'], date_str,
                        hours, existing.get('note', ''),
                    )
                    existing['actual_hours'] = hours
                else:
                    new_id   = db.add_actual(worker['id'], task['id'], date_str, hours)
                    existing = db.get_actual_by_id(new_id)
                    self._actual_lu[(worker['id'], task['id'], date_str)] = existing
            else:
                if existing:
                    db.delete_actual(existing['id'])
                    self._actual_lu.pop((worker['id'], task['id'], date_str), None)
                    existing = None

        # UserRole + 表示テキストを更新
        meta['hours']    = hours
        meta['existing'] = existing
        self._loading = True
        item.setText(_fmt(hours))
        item.setData(Qt.UserRole, meta)
        self._loading = False

        # 月計列を再計算
        self._update_total_col(row)

    def _update_total_col(self, row: int):
        tot_col = self.table.columnCount() - 1
        total   = 0.0
        for c in range(self.N_FIXED, tot_col):
            it = self.table.item(row, c)
            if it:
                t = it.text().strip()
                try:
                    total += float(t) if t else 0.0
                except ValueError:
                    pass
        self._loading = True
        tot_it = self.table.item(row, tot_col)
        if tot_it:
            tot_it.setText(_fmt(total))
        self._loading = False

    # ── 行追加 ────────────────────────────────────────────────────────────────

    def _add_row_dialog(self):
        workers = db.get_all_workers()
        tasks   = db.get_all_tasks()
        if not workers or not tasks:
            QMessageBox.warning(self, "マスタ未登録",
                                "担当者・作業をマスタ管理タブで先に登録してください")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("行を追加（担当者・作業）")
        dlg.setMinimumWidth(320)
        fl = QFormLayout(dlg)

        w_combo = QComboBox()
        for w in workers:
            w_combo.addItem(w['name'], w['id'])
        t_combo = _make_editable_task_combo(tasks)
        fl.addRow("担当者:", w_combo)
        fl.addRow("作業名:", t_combo)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)

        if dlg.exec_() == QDialog.Accepted:
            wid = w_combo.currentData()
            tid = resolve_task_combo(t_combo)
            if wid and tid:
                self._pinned_pairs.add((wid, tid))
                self._build_table()
