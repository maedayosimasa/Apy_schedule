"""
2週間ガントチャートタブ

  操作:
    ドラッグ選択   … 複数日セルをまたいでドラッグ → 連続予定ダイアログ
    ダブルクリック … 単一セル追加 / スパンバー編集
    右クリック     … コンテキストメニュー（追加/編集/削除/実績入力）

  表示:
    連続した予定は1本のスパンバーで結合表示
    バー色はステータス別、緑▲は実績登録済みマーカー
"""
import json
from datetime import date, timedelta
from itertools import groupby

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QDateEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QMenu, QDialog, QMessageBox, QHeaderView,
    QFormLayout, QDialogButtonBox, QStyledItemDelegate, QLineEdit,
    QTextEdit, QGroupBox, QSizePolicy, QColorDialog, QSpinBox,
    QFrame, QApplication,
)
from PyQt5.QtCore import (
    Qt, QDate, QSize, QPoint, QRect, QTimer, QEvent,
    QItemSelection, QItemSelectionModel, pyqtSignal,
)
from PyQt5.QtGui import (
    QColor, QFont, QFontMetrics, QPainter, QBrush, QPen, QDoubleValidator, QPainterPath,
)

import database as db
from holidays import get_holiday
from ui.dialogs import GanttScheduleDialog, ActualDialog, \
    _make_editable_task_combo, resolve_task_combo
from ui.zoom_mixin import ZoomMixin, ZoomableTableWidget

_WEEKDAY = ['月', '火', '水', '木', '金', '土', '日']


def _nonwork_gap_only(d1: date, d2: date) -> bool:
    """d1 の翌日〜 d2 の前日が全て土日または祝日なら True。
    隣接日（d2 == d1+1）の場合は間の日がないため常に True を返す。"""
    cur = d1 + timedelta(days=1)
    while cur < d2:
        if cur.weekday() < 5 and not get_holiday(cur):
            return False
        cur += timedelta(days=1)
    return True

_STATUS_COLORS = {
    # 凡例表示用（variants[0] のみ使用）
    'planned':     [('#64B5F6', '#1565C0')],
    'in_progress': [('#FFD54F', '#E65100')],
    'completed':   [('#81C784', '#2E7D32')],
    'cancelled':   [('#EF9A9A', '#B71C1C')],
}

# 作業ごとのバー塗りつぶし色（隣接行が異なる色になるよう6色用意）
_TASK_PALETTE = [
    '#64B5F6',  # 水色
    '#81C784',  # 緑
    '#FFD54F',  # 黄
    '#CE93D8',  # 紫
    '#FF8A65',  # 橙
    '#80CBC4',  # ティール
]
# ステータス別の境界・文字色（バー内テキストとアウトラインに使用）
_STATUS_BORDER = {
    'planned':     '#1565C0',
    'in_progress': '#E65100',
    'completed':   '#2E7D32',
    'cancelled':   '#B71C1C',
}
_STATUS_LABELS = {
    'planned': '予定', 'in_progress': '進行中',
    'completed': '完了', 'cancelled': 'キャンセル',
}

_DRAG_THRESHOLD = 4   # ドラッグ開始とみなす最小移動ピクセル数


def _bar_path(rect: QRect, radius: int, round_left: bool, round_right: bool) -> QPainterPath:
    """片側のみ角丸の矩形パスを返す。"""
    r = float(min(radius, rect.height() // 2))
    x, y = float(rect.x()), float(rect.y())
    w, h = float(rect.width()), float(rect.height())
    p = QPainterPath()
    p.moveTo(x + (r if round_left else 0), y)
    p.lineTo(x + w - (r if round_right else 0), y)
    if round_right:
        p.quadTo(x + w, y, x + w, y + r)
    p.lineTo(x + w, y + h - (r if round_right else 0))
    if round_right:
        p.quadTo(x + w, y + h, x + w - r, y + h)
    p.lineTo(x + (r if round_left else 0), y + h)
    if round_left:
        p.quadTo(x, y + h, x, y + h - r)
    p.lineTo(x, y + (r if round_left else 0))
    if round_left:
        p.quadTo(x, y, x + r, y)
    p.closeSubpath()
    return p


# ─── delegate ─────────────────────────────────────────────────────────────────

class _GanttDelegate(QStyledItemDelegate):

    def __init__(self, tab=None):
        super().__init__(tab)
        self._tab         = tab
        self._pending_key = ''   # 数字キー直接入力の先行文字

    def paint(self, painter, option, index):
        data = index.data(Qt.UserRole)
        if not isinstance(data, dict) or data.get('type') != 'date_cell':
            super().paint(painter, option, index)
            return

        painter.save()
        rect  = option.rect
        d_obj = data.get('date_obj')
        today = date.today()

        # ── 背景（優先度: 今日 > 祝日 > 土日 > 通常、行交互色）────────────
        is_odd    = index.row() % 2 == 1
        holiday   = get_holiday(d_obj) if d_obj else ''
        if d_obj == today:
            bg = QColor('#FFFDE7')
        elif holiday:
            bg = QColor('#FFD9DC') if is_odd else QColor('#FFEBEE')
        elif d_obj and d_obj.weekday() >= 5:
            bg = QColor('#E6EEF3') if is_odd else QColor('#EEEEEE')
        else:
            bg = QColor('#E8F4FD') if is_odd else QColor('#FFFFFF')

        mid_y    = rect.top() + rect.height() // 2
        sched    = data.get('schedule')
        span_pos = data.get('span_pos', 'single')   # 'single'|'start'|'middle'|'end'

        # middle/end または隣テキストはみ出し対象セルは下半分のみ塗る（上半分を上書きしない）
        if (sched and span_pos in ('middle', 'end')) or data.get('top_half_clear'):
            painter.fillRect(
                QRect(rect.left(), mid_y, rect.width(), rect.height() - rect.height() // 2),
                bg,
            )
        else:
            painter.fillRect(rect, bg)

        # ── 予定バー（上半分・start/single のみ描画）─────────────────────────
        if sched and span_pos in ('single', 'start'):
            status    = sched.get('status', 'planned')
            task_cidx = data.get('task_color_idx', 0)
            fill_h    = _TASK_PALETTE[task_cidx % len(_TASK_PALETTE)]
            bord_h    = _STATUS_BORDER.get(status, '#1565C0')

            top_y  = rect.top() + 2
            text_h = 12                               # テキスト領域の高さ
            bar_y  = top_y + text_h + 1               # バーはテキストの下
            bar_h  = max(3, mid_y - bar_y - 2)        # 上半分に収まる高さ
            lm, rm = 2, 2

            # バー幅（連続スパン分を合計）
            span_len = data.get('span_len', 1)
            if self._tab and span_len > 1:
                bar_w = sum(
                    self._tab.table.columnWidth(index.column() + j)
                    for j in range(span_len)
                )
            else:
                bar_w = rect.width()

            # テキスト文字列
            task_obj  = data.get('task', {})
            work_item = sched.get('note', '')
            category  = task_obj.get('category', '')
            text      = work_item or category or task_obj.get('title', '')
            f = QFont("Yu Gothic UI"); f.setPointSize(7)

            # テキスト描画幅：右隣に予定のない空きセルがあれば文字が収まるまで拡張
            text_w = bar_w
            if self._tab:
                _needed = QFontMetrics(f).horizontalAdvance(text) + 10
                if _needed > bar_w:
                    _extra, _col = 0, index.column() + span_len
                    _nc = self._tab.table.columnCount()
                    while _col < _nc and _extra + bar_w < _needed:
                        _adj = self._tab.table.item(index.row(), _col)
                        _ad  = _adj.data(Qt.UserRole) if _adj else None
                        if _ad and _ad.get('schedule'):
                            break
                        _extra += self._tab.table.columnWidth(_col)
                        _col   += 1
                    text_w = bar_w + _extra

            bar  = QRect(rect.left() + lm, bar_y, bar_w - lm - rm, bar_h)
            path = _bar_path(bar, 3, True, True)

            # バーをスパン幅でクリップして描画
            painter.setClipRect(
                QRect(rect.left(), rect.top(), bar_w + 4, rect.height()),
                Qt.ReplaceClip,
            )
            painter.setBrush(QBrush(QColor(fill_h)))
            painter.setPen(QPen(QColor(bord_h), 1))
            painter.drawPath(path)

            # テキストを空き領域まで拡張したクリップで描画
            painter.setClipRect(
                QRect(rect.left(), rect.top(), text_w + 4, rect.height()),
                Qt.ReplaceClip,
            )
            painter.setFont(f)
            text_color = data.get('text_color') or bord_h
            painter.setPen(QPen(QColor(text_color)))
            painter.drawText(
                QRect(rect.left() + 3, top_y, text_w - 6, text_h),
                Qt.AlignVCenter | Qt.AlignLeft, text,
            )

            # restore clip to this cell before drawing actuals / grid
            painter.setClipRect(option.rect, Qt.ReplaceClip)

        # ── 実績テキスト（下半分・バーなし）─────────────────────────────────
        actual       = data.get('actual')
        actual_hours = actual.get('actual_hours', 0) if actual else None

        act_area = QRect(rect.left() + 3, mid_y + 1,
                         rect.width() - 6, rect.bottom() - mid_y - 2)

        if actual_hours is not None and actual_hours > 0:
            actual_note = (actual or {}).get('note', '')
            _af = QFont("Yu Gothic UI"); _af.setPointSize(7)
            painter.setFont(_af)
            painter.setPen(QPen(QColor('#1B5E20')))
            hours_str = f'{actual_hours:.1f}h'
            display   = f'{hours_str} {actual_note}' if actual_note else hours_str
            painter.drawText(act_area, Qt.AlignVCenter | Qt.AlignLeft, display)
        elif d_obj and d_obj <= today:
            # 過去・当日で実績未入力 → 点線で入力促す（予定の有無を問わない）
            pen = QPen(QColor('#BDBDBD'), 1, Qt.DashLine)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(pen)
            painter.drawRoundedRect(
                QRect(rect.left() + 2, mid_y + 1, rect.width() - 4, rect.bottom() - mid_y - 2),
                3, 3,
            )

        # ── ギャップバー（予定スパン内の土日祝日を薄く塗る）─────────────────
        if data.get('span_gap'):
            task_cidx  = data.get('task_color_idx', 0)
            g_fill     = _TASK_PALETTE[task_cidx % len(_TASK_PALETTE)]
            g_color    = QColor(g_fill)
            g_color.setAlpha(80)   # 薄く塗って「同じ予定の続き」を示す
            _gap_bar_y = rect.top() + 2 + 12 + 1      # メインバーと同じ位置
            _gap_bar_h = max(3, mid_y - _gap_bar_y - 2)
            painter.fillRect(QRect(rect.left(), _gap_bar_y, rect.width(), _gap_bar_h), g_color)

        # ── 選択ハイライト ────────────────────────────────────────────────────
        if option.state & 0x0002:   # State_Selected
            painter.fillRect(rect, QColor(25, 118, 210, 55))

        # ── グリッド ──────────────────────────────────────────────────────────
        painter.setPen(QPen(QColor('#E0E0E0'), 1))
        if span_pos in ('start', 'middle') or data.get('span_gap'):
            # スパン途中・ギャップセルは上半分の縦線を引かずバーを連続させる
            painter.drawLine(rect.right(), mid_y, rect.right(), rect.bottom())
        else:
            painter.drawLine(rect.right(), rect.top(), rect.right(), rect.bottom())
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        # ── 担当者境界ライン ──────────────────────────────────────────────────
        if data.get('worker_boundary'):
            painter.setPen(QPen(QColor('#455A64'), 2))
            painter.drawLine(rect.left(), rect.top(), rect.right(), rect.top())

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(62, 46)

    # ── インライン編集（実績時間の直接入力）──────────────────────────────────

    def createEditor(self, parent, option, index):
        data = index.data(Qt.UserRole)
        if not isinstance(data, dict) or data.get('type') != 'date_cell':
            return None
        ed = QLineEdit(parent)
        ed.setValidator(QDoubleValidator(0.0, 24.0, 1, ed))
        ed.setAlignment(Qt.AlignCenter)
        ed.setStyleSheet(
            "QLineEdit {"
            "  background-color: #FFFFFF;"
            "  color: #1B5E20;"
            "  border: 2px solid #2E7D32;"
            "  border-radius: 3px;"
            "  font-size: 11px;"
            "  font-weight: bold;"
            "}"
        )
        return ed

    def setEditorData(self, editor, index):
        data   = index.data(Qt.UserRole)
        actual = (data or {}).get('actual')
        hours  = actual.get('actual_hours', 0) if actual else 0
        if self._pending_key:
            editor.setText(self._pending_key)
            self._pending_key = ''
        else:
            editor.setText('' if hours <= 0 else
                           str(int(hours)) if hours == int(hours) else f'{hours:.1f}')
        editor.selectAll()

    def updateEditorGeometry(self, editor, option, index):
        rect = option.rect
        editor.setGeometry(
            QRect(rect.left() + 1, rect.top() + 1,
                  rect.width() - 2, rect.height() - 2)
        )

    def setModelData(self, editor, model, index):
        text = editor.text().strip()
        try:
            hours = float(text) if text else 0.0
        except ValueError:
            return
        hours = max(0.0, min(24.0, hours))

        data = index.data(Qt.UserRole)
        if not isinstance(data, dict) or data.get('type') != 'date_cell':
            return

        worker   = data['worker']
        task     = data['task']
        date_str = data['date']
        actual   = data.get('actual')

        if hours > 0:
            if actual:
                db.update_actual(
                    actual['id'], worker['id'], task['id'],
                    date_str, hours, actual.get('note', ''),
                )
                actual['actual_hours'] = hours
            else:
                new_id = db.add_actual(worker['id'], task['id'], date_str, hours)
                actual = db.get_actual_by_id(new_id)
        else:
            if actual:
                db.delete_actual(actual['id'])
                actual = None

        data['actual'] = actual
        if self._tab:
            it = self._tab.table.item(index.row(), index.column())
            if it:
                it.setData(Qt.UserRole, data)
                note = (actual or {}).get('note', '')
                it.setToolTip(note)
            self._tab.actuals_changed.emit()


# ─── fixed-table delegate (worker boundary lines) ────────────────────────────

class _WorkerBoundaryDelegate(QStyledItemDelegate):
    """固定列テーブル用：担当者グループの先頭行の上端に太い境界線を描画する。"""

    def __init__(self, tab=None):
        super().__init__(tab)
        self._tab = tab

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if self._tab and index.row() in self._tab._worker_boundary_rows:
            painter.save()
            painter.setPen(QPen(QColor('#455A64'), 2))
            r = option.rect
            painter.drawLine(r.left(), r.top(), r.right(), r.top())
            painter.restore()


# ─── drop indicator overlay ───────────────────────────────────────────────────

class _DropLineWidget(QWidget):
    """行ドラッグ時の挿入位置を示す水平ラインをビューポート上に描画する。"""

    def __init__(self, table):
        super().__init__(table)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._y = 0
        self.hide()

    def show_at(self, y: int):
        vp = self.parent().viewport()
        vp_pos = vp.pos()
        self.setGeometry(vp_pos.x(), vp_pos.y(), vp.width(), vp.height())
        self._y = y
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QPen(QColor('#1976D2'), 2))
        p.drawLine(0, self._y, self.width(), self._y)
        # 両端に三角マーカー
        for x in (0, self.width() - 1):
            p.drawLine(x, self._y - 4, x, self._y + 4)


# ─── main tab ─────────────────────────────────────────────────────────────────

class GanttTab(QWidget, ZoomMixin):
    N_FIXED = 3   # 担当者 | 作業名 | 計(h)
    actuals_changed = pyqtSignal()   # 実績の追加/編集/削除時に emit

    def __init__(self):
        super().__init__()
        self._dates:                list = []
        self._rows:                 list = []
        self._pinned_pairs:         set  = set()
        self._row_order:            list = []   # (worker_id, task_id) の表示順リスト
        self._worker_boundary_rows: set  = set()  # 担当者が変わる行インデックス

        # スナップショットモード
        self._snapshot_mode:  bool = False   # True=過去の確認モード
        self._snapshot_data:  dict | None = None   # 表示中のスナップショット

        # 列幅・行高さの保存（ユーザー変更を refresh 後も維持）
        _fm = QApplication.instance().fontMetrics()
        self._row_heights_by_pair: dict = {}
        self._fixed_col_widths: list = [
            _fm.horizontalAdvance("山田 太郎") + 20,
            _fm.horizontalAdvance("作業名テストABCDE") + 20,
            _fm.horizontalAdvance("99.9") + 16,
        ]
        self._default_date_col_w: int = _fm.horizontalAdvance("8.0") + 16
        self._default_row_h:      int = max(_fm.height() * 3 + 4, 40)
        self._date_col_widths: dict = {}       # date_str -> width
        self._building_table: bool = False
        self._header_h: int = 20   # ヘッダー行の高さ（_sync_header_height で確定）

        # レイアウト保存タイマー（列幅・行高さをリサイズ後 400ms でバッチ保存）
        self._layout_save_timer = QTimer()
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.setInterval(400)
        self._layout_save_timer.timeout.connect(self._save_all_layout)

        self._load_layout_settings()
        self._init_zoom("zoom_gantt")

        # セルスパンドラッグ状態（予定の連続作成）
        self._drag_start_pos  = None
        self._drag_row        = -1
        self._drag_col_start  = -1
        self._drag_col_end    = -1
        self._dragging        = False

        # 行並び替えドラッグ状態
        self._rdrag_start_pos = None
        self._rdrag_src_row   = -1
        self._rdrag_dst_row   = -1
        self._rdrag_active    = False

        self._setup_ui()
        # 保存済みの検討事項を復元
        saved = db.get_setting('gantt_note')
        if saved:
            self.gantt_note.setPlainText(saved)
        self._apply_zoom()
        QTimer.singleShot(0, self.refresh)

    # ── setup ─────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # ── コントロール行 ─────────────────────────────────────────────────────
        cl = QHBoxLayout()
        cl.addWidget(QLabel("担当者:"))
        self.worker_filter = QComboBox()
        self.worker_filter.setMinimumWidth(110)
        cl.addWidget(self.worker_filter)

        cl.addWidget(QLabel("  開始:"))
        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDate(QDate.currentDate().addDays(-7))
        cl.addWidget(self.from_date)

        cl.addWidget(QLabel("〜"))
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDate(QDate.currentDate().addDays(30))
        cl.addWidget(self.to_date)

        for label, delta in [("◀2週", -14), ("2週▶", 14)]:
            btn = QPushButton(label)
            btn.setFixedWidth(52)
            btn.clicked.connect(lambda _, d=delta: self._shift(d))
            cl.addWidget(btn)

        today_btn = QPushButton("今日")
        today_btn.setFixedWidth(46)
        today_btn.clicked.connect(self._goto_today)
        cl.addWidget(today_btn)

        refresh_btn = QPushButton("更新")
        refresh_btn.setFixedWidth(46)
        refresh_btn.clicked.connect(self.refresh)
        cl.addWidget(refresh_btn)

        self._make_zoom_controls(cl)
        cl.addStretch()
        layout.addLayout(cl)

        # ── スナップショット行 ──────────────────────────────────────────────────
        sl = QHBoxLayout()

        save_snap_btn = QPushButton("📷 今日の予定を保存")
        save_snap_btn.setToolTip("今日の予定状態をスナップショットとして保存します（上書き）")
        save_snap_btn.setStyleSheet(
            "QPushButton { background-color: #388E3C; }"
            "QPushButton:hover { background-color: #2E7D32; }"
        )
        save_snap_btn.clicked.connect(self._save_snapshot_manual)
        sl.addWidget(save_snap_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFrameShadow(QFrame.Sunken)
        sl.addWidget(sep)

        self._snap_toggle_btn = QPushButton("🔍 過去の予定を確認")
        self._snap_toggle_btn.setCheckable(True)
        self._snap_toggle_btn.setToolTip("保存済みスナップショットを選んで過去の予定を表示します")
        self._snap_toggle_btn.setStyleSheet(
            "QPushButton { background-color: #1976D2; }"
            "QPushButton:checked { background-color: #E65100; }"
            "QPushButton:hover { background-color: #1565C0; }"
        )
        self._snap_toggle_btn.toggled.connect(self._on_snapshot_mode_toggled)
        sl.addWidget(self._snap_toggle_btn)

        self._snap_date_combo = QComboBox()
        self._snap_date_combo.setMinimumWidth(130)
        self._snap_date_combo.setToolTip("確認したいスナップショットの日付を選択")
        self._snap_date_combo.setEnabled(False)
        self._snap_date_combo.currentIndexChanged.connect(self._on_snapshot_date_changed)
        sl.addWidget(self._snap_date_combo)

        self._snap_info_label = QLabel("")
        self._snap_info_label.setStyleSheet("color: #E65100; font-weight: bold;")
        sl.addWidget(self._snap_info_label)

        sl.addStretch()

        cl2 = QHBoxLayout()
        cl2.addLayout(sl)
        cl2.addWidget(QLabel("  ヘッダー高さ:"))
        self.header_height_spin = QSpinBox()
        self.header_height_spin.setRange(16, 80)
        self.header_height_spin.setSuffix(" px")
        self.header_height_spin.setValue(self._header_h)
        self.header_height_spin.setFixedWidth(72)
        self.header_height_spin.setToolTip("ガントチャートのヘッダー行の高さを変更")
        self.header_height_spin.valueChanged.connect(self._on_header_height_changed)
        cl2.addWidget(self.header_height_spin)
        cl2.addStretch()
        layout.addLayout(cl2)

        # ── 凡例 + 行追加ボタン ────────────────────────────────────────────────
        ll = QHBoxLayout()
        ll.addWidget(QLabel("凡例: "))
        for st, variants in _STATUS_COLORS.items():
            fill, bord = variants[0]
            lbl = QLabel(f"■ {_STATUS_LABELS[st]}")
            lbl.setStyleSheet(
                f"color:{bord}; background:{fill}; padding:1px 6px;"
                f" border:1px solid {bord}; border-radius:3px; font-size:11px;"
            )
            ll.addWidget(lbl)
        ll.addWidget(QLabel("  ■実績あり(下段:緑)"))
        ll.addStretch()

        add_row_btn = QPushButton("+ 行を追加")
        add_row_btn.setFixedWidth(90)
        add_row_btn.clicked.connect(self._add_row_dialog)
        ll.addWidget(add_row_btn)
        layout.addLayout(ll)

        # ── 固定列テーブル（担当者・作業名・計）────────────────────────────────
        self.fixed_table = ZoomableTableWidget()
        self.fixed_table.setColumnCount(self.N_FIXED)
        self.fixed_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.fixed_table.horizontalHeader().setMinimumSectionSize(20)
        self.fixed_table.verticalHeader().setVisible(False)
        self.fixed_table.setShowGrid(False)
        self.fixed_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.fixed_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.fixed_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.fixed_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.fixed_table.setFocusPolicy(Qt.NoFocus)
        self.fixed_table.setFixedWidth(100 + 140 + 48 + 4)   # 担当者+作業名+計+border
        self.fixed_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.fixed_table.customContextMenuRequested.connect(self._on_fixed_context_menu)
        self.fixed_table.viewport().installEventFilter(self)
        self._boundary_delegate = _WorkerBoundaryDelegate(self)
        self.fixed_table.setItemDelegate(self._boundary_delegate)

        # ── 日付テーブル（横スクロール可）────────────────────────────────────
        self.table = ZoomableTableWidget()
        self._delegate = _GanttDelegate(self)
        self.table.setItemDelegate(self._delegate)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.ContiguousSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setMinimumSectionSize(20)
        self.table.verticalHeader().setVisible(True)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.verticalHeader().setDefaultSectionSize(self._default_row_h)
        self.table.verticalHeader().setMinimumSectionSize(20)
        self.table.verticalHeader().setFixedWidth(10)
        self.table.verticalHeader().setStyleSheet(
            "QHeaderView::section { background:#E0E0E0; border:none; padding:0px; }"
        )
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        self.table.viewport().installEventFilter(self)
        self.table.installEventFilter(self)
        self._register_zoom_table(self.fixed_table, self.table)

        self._drop_line = _DropLineWidget(self.fixed_table)

        # 垂直スクロールを同期
        self.table.verticalScrollBar().valueChanged.connect(
            self.fixed_table.verticalScrollBar().setValue)
        self.fixed_table.verticalScrollBar().valueChanged.connect(
            self.table.verticalScrollBar().setValue)

        # 列幅・行高さのリサイズをテーブル間で同期
        self.fixed_table.horizontalHeader().sectionResized.connect(self._on_fixed_col_resized)
        self.table.horizontalHeader().sectionResized.connect(self._on_date_col_resized)
        self.table.verticalHeader().sectionResized.connect(self._on_row_resized)

        table_hbox = QHBoxLayout()
        table_hbox.setSpacing(0)
        table_hbox.setContentsMargins(0, 0, 0, 0)
        table_hbox.addWidget(self.fixed_table)
        table_hbox.addWidget(self.table, 1)
        layout.addLayout(table_hbox)

        hint_lbl = QLabel(
            "担当者/作業名列ドラッグ: 行を移動    "
            "日付列ドラッグ: 複数日予定を一括作成    "
            "ダブルクリック上段: 予定追加/編集    "
            "ダブルクリック下段 / 数字キー: 実績直接入力    "
            "右クリック: メニュー"
        )
        layout.addWidget(hint_lbl)

        # ── 検討事項エリア ────────────────────────────────────────────────────
        note_box = QGroupBox("検討事項")
        note_vl  = QVBoxLayout(note_box)
        note_vl.setContentsMargins(6, 4, 6, 6)
        self.gantt_note = QTextEdit()
        self.gantt_note.setPlaceholderText("ここに検討事項・メモを自由に入力できます…")
        self.gantt_note.setFixedHeight(90)
        self.gantt_note.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.gantt_note.setStyleSheet(
            "QTextEdit {"
            "  background-color: #FFFDE7;"
            "  border: 1px solid #F9A825;"
            "  border-radius: 4px;"
            "  font-size: 12px;"
            "  padding: 2px 4px;"
            "}"
        )
        note_vl.addWidget(self.gantt_note)
        layout.addWidget(note_box)

        # 自動保存タイマー（入力後 1 秒で保存）
        self._note_save_timer = QTimer()
        self._note_save_timer.setSingleShot(True)
        self._note_save_timer.setInterval(1000)
        self._note_save_timer.timeout.connect(self._save_gantt_note)
        self.gantt_note.textChanged.connect(
            lambda: self._note_save_timer.start()
        )

    # ── イベントフィルタ ──────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        # ── テーブル本体のキーイベント：数字キーで実績直接入力 ────────────────
        if obj is self.table and event.type() == QEvent.KeyPress:
            key = event.key()
            if Qt.Key_0 <= key <= Qt.Key_9 or key == Qt.Key_Period:
                cur = self.table.currentIndex()
                if cur.isValid() and cur.column() >= 0:
                    data = self._cell_data(cur.row(), cur.column())
                    if data and data.get('type') == 'date_cell':
                        self._delegate._pending_key = event.text()
                        self._open_actual_inline(cur.row(), cur.column())
                        return True
            return False

        # ── 固定列テーブル（行並び替えドラッグ）────────────────────────────────
        if obj is self.fixed_table.viewport():
            t = event.type()
            if t == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                row = self.fixed_table.rowAt(event.pos().y())
                if row >= 0:
                    self._rdrag_start_pos = event.pos()
                    self._rdrag_src_row   = row
                    self._rdrag_dst_row   = row
                    self._rdrag_active    = False
                    self._drag_start_pos  = None
                return False
            elif t == QEvent.MouseMove:
                if not (event.buttons() & Qt.LeftButton) or self._rdrag_start_pos is None:
                    return False
                dist = (event.pos() - self._rdrag_start_pos).manhattanLength()
                if dist > _DRAG_THRESHOLD:
                    self._rdrag_active = True
                if self._rdrag_active:
                    self._rdrag_dst_row = self._calc_drop_row(event.pos().y())
                    self._update_row_drag_indicator()
                    return True
                return False
            elif t == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                if self._rdrag_active:
                    src, dst = self._rdrag_src_row, self._rdrag_dst_row
                    self._rdrag_start_pos = None
                    self._rdrag_active    = False
                    self._rdrag_src_row   = -1
                    self._drop_line.hide()
                    self._reorder_row(src, dst)
                    return True
                self._rdrag_start_pos = None
                self._rdrag_active    = False
                return False
            return False

        if obj is not self.table.viewport():
            return super().eventFilter(obj, event)

        t = event.type()

        # ── マウス押下：ドラッグ開始記録 ──────────────────────────────────────
        if t == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            row = self.table.rowAt(event.pos().y())
            col = self.table.columnAt(event.pos().x())
            if row >= 0 and col >= 0:
                # 日付列 → 予定スパンドラッグ
                self._drag_start_pos = event.pos()
                self._drag_row       = row
                self._drag_col_start = col
                self._drag_col_end   = col
                self._dragging       = False
                self._rdrag_start_pos = None
            else:
                self._drag_start_pos  = None
                self._rdrag_start_pos = None
            return False   # 通常選択も動かす

        # ── マウス移動 ──────────────────────────────────────────────────────────
        elif t == QEvent.MouseMove:
            if not (event.buttons() & Qt.LeftButton):
                self._drag_start_pos  = None
                self._rdrag_start_pos = None
                return False

            # 行並び替えドラッグ中
            if self._rdrag_start_pos is not None:
                dist = (event.pos() - self._rdrag_start_pos).manhattanLength()
                if dist > _DRAG_THRESHOLD:
                    self._rdrag_active = True
                if self._rdrag_active:
                    self._rdrag_dst_row = self._calc_drop_row(event.pos().y())
                    self._update_row_drag_indicator()
                    return True
                return False

            # 予定スパンドラッグ中
            if self._drag_start_pos is None:
                return False

            dist = (event.pos() - self._drag_start_pos).manhattanLength()
            if dist > _DRAG_THRESHOLD:
                self._dragging = True

            if self._dragging:
                cur_row = self.table.rowAt(event.pos().y())
                cur_col = self.table.columnAt(event.pos().x())
                # 同一行・日付列のみ
                if cur_row == self._drag_row and cur_col >= 0:
                    self._drag_col_end = cur_col
                    self._update_drag_selection()
                return True   # デフォルト選択を抑制

            return False

        # ── マウス離し：ドラッグ完了 ──────────────────────────────────────────
        elif t == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            # 行並び替えドラッグ完了
            if self._rdrag_active:
                src = self._rdrag_src_row
                dst = self._rdrag_dst_row
                self._rdrag_start_pos = None
                self._rdrag_active    = False
                self._rdrag_src_row   = -1
                self._rdrag_dst_row   = -1
                self._drop_line.hide()
                self._reorder_row(src, dst)
                return True

            self._rdrag_start_pos = None
            self._rdrag_active    = False

            # 予定スパンドラッグ完了
            if self._dragging and self._drag_start_pos is not None:
                c0 = min(self._drag_col_start, self._drag_col_end)
                c1 = max(self._drag_col_start, self._drag_col_end)
                row = self._drag_row
                self._drag_start_pos = None
                self._dragging       = False
                self.table.clearSelection()

                if c1 > c0:   # 複数セル選択
                    self._open_range_dialog(row, c0, c1)
                    return True

            self._drag_start_pos = None
            self._dragging       = False
            return False

        # ── ダブルクリック：上半分→予定編集、下半分→実績インライン入力 ──────────
        elif t == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            row = self.table.rowAt(event.pos().y())
            col = self.table.columnAt(event.pos().x())
            if row >= 0 and col >= 0:
                data = self._cell_data(row, col)
                if data and data.get('type') == 'date_cell':
                    cell_top = self.table.rowViewportPosition(row)
                    mid_y    = cell_top + self.table.rowHeight(row) // 2
                    if event.pos().y() >= mid_y:
                        # 下半分 → 実績をインラインエディタで直接入力
                        # （ダブルクリックイベントの処理完了後に実行するため遅延）
                        self._delegate._pending_key = ''
                        _r, _c = row, col
                        QTimer.singleShot(0, lambda: self._open_actual_inline(_r, _c))
                    else:
                        # 上半分 → 予定編集/追加
                        self._edit_or_add_schedule(data)
                    return True
            return False

        return super().eventFilter(obj, event)

    def _update_drag_selection(self):
        row = self._drag_row
        c0  = min(self._drag_col_start, self._drag_col_end)
        c1  = max(self._drag_col_start, self._drag_col_end)
        m   = self.table.model()
        sel = QItemSelection(m.index(row, c0), m.index(row, c1))
        self.table.selectionModel().select(sel, QItemSelectionModel.ClearAndSelect)

    def _calc_drop_row(self, y_in_viewport: int) -> int:
        """マウスY座標から挿入位置（何行目の前に挿入するか）を返す。"""
        n = len(self._rows)
        if n == 0:
            return 0
        for r in range(n):
            top = self.fixed_table.rowViewportPosition(r)
            h   = self.fixed_table.rowHeight(r)
            if y_in_viewport <= top + h // 2:
                return r
        return n  # 末尾に追加

    def _update_row_drag_indicator(self):
        """ドラッグ中の挿入位置インジケーターを更新する。"""
        dst = self._rdrag_dst_row
        n   = len(self._rows)
        if dst >= n:
            last = n - 1
            y = self.fixed_table.rowViewportPosition(last) + self.fixed_table.rowHeight(last)
        else:
            y = self.fixed_table.rowViewportPosition(dst)
        self._drop_line.show_at(y)

    def _reorder_row(self, src: int, insert_before: int):
        """_row_order の src 番目の行を insert_before 番目の前に移動する。"""
        n = len(self._row_order)
        if not (0 <= src < n):
            return
        insert_before = max(0, min(n, insert_before))
        if insert_before in (src, src + 1):
            return  # 移動なし
        pair = self._row_order.pop(src)
        new_pos = insert_before if insert_before <= src else insert_before - 1
        self._row_order.insert(new_pos, pair)
        self._save_row_order()
        self._build_table()

    # ── ナビゲーション ────────────────────────────────────────────────────────

    def _shift(self, days: int):
        self.from_date.setDate(self.from_date.date().addDays(days))
        self.to_date.setDate(self.to_date.date().addDays(days))
        self.refresh()

    def _goto_today(self):
        t = QDate.currentDate()
        self.from_date.setDate(t.addDays(-7))
        self.to_date.setDate(t.addDays(30))
        self.refresh()

    # ── インライン実績入力の共通起動 ──────────────────────────────────────────

    def _open_actual_inline(self, row: int, col: int):
        """指定セルのインラインエディタを開く（実績時間の直接入力）"""
        idx = self.table.model().index(row, col)
        self.table.setCurrentIndex(idx)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.table.edit(idx)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)

    def _save_gantt_note(self):
        db.set_setting('gantt_note', self.gantt_note.toPlainText())

    # ── スナップショット操作 ──────────────────────────────────────────────────

    def _save_snapshot_manual(self):
        """ユーザーが手動で今日のスナップショットを保存する。"""
        from datetime import date as _date
        today = _date.today().strftime('%Y-%m-%d')
        db.save_snapshot(today)
        self._reload_snapshot_dates()
        QMessageBox.information(
            self, "保存完了",
            f"今日（{today}）の予定をスナップショットとして保存しました。"
        )

    def _reload_snapshot_dates(self):
        """スナップショット日付コンボボックスを最新化する。"""
        self._snap_date_combo.blockSignals(True)
        prev = self._snap_date_combo.currentData()
        self._snap_date_combo.clear()
        for d in db.get_snapshot_dates():
            self._snap_date_combo.addItem(d, d)
        # 以前の選択を復元
        if prev:
            idx = self._snap_date_combo.findData(prev)
            if idx >= 0:
                self._snap_date_combo.setCurrentIndex(idx)
        self._snap_date_combo.blockSignals(False)

    def _on_snapshot_mode_toggled(self, checked: bool):
        self._snapshot_mode = checked
        self._snap_date_combo.setEnabled(checked)
        if checked:
            self._reload_snapshot_dates()
            if self._snap_date_combo.count() == 0:
                QMessageBox.information(
                    self, "スナップショットなし",
                    "保存済みのスナップショットがありません。\n"
                    "「📷 今日の予定を保存」で保存してから確認してください。"
                )
                self._snap_toggle_btn.setChecked(False)
                return
            self._load_snapshot(self._snap_date_combo.currentData())
        else:
            self._snapshot_data = None
            self._snap_info_label.setText("")
            self.refresh()

    def _on_snapshot_date_changed(self, idx: int):
        if not self._snapshot_mode:
            return
        date_str = self._snap_date_combo.itemData(idx)
        if date_str:
            self._load_snapshot(date_str)

    def _load_snapshot(self, date_str: str):
        snap = db.get_snapshot(date_str)
        if snap is None:
            QMessageBox.warning(self, "エラー", f"{date_str} のスナップショットが見つかりません。")
            return
        self._snapshot_data = snap
        self._snap_info_label.setText(f"📅 {date_str} 時点の予定（読み取り専用）")
        self._build_table()

    # ── public ────────────────────────────────────────────────────────────────

    def refresh(self):
        if self._snapshot_mode:
            return   # スナップショットモード中は自動リフレッシュで上書きしない
        self._reload_worker_filter()
        self._build_table()

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

    def _get_dates(self) -> list:
        qf = self.from_date.date()
        qt = self.to_date.date()
        d0 = date(qf.year(), qf.month(), qf.day())
        d1 = date(qt.year(), qt.month(), qt.day())
        out, d = [], d0
        while d <= d1:
            out.append(d); d += timedelta(days=1)
        return out

    def _build_table(self):
        self._building_table = True
        today       = date.today()
        self._dates = self._get_dates()
        if not self._dates:
            self._building_table = False
            return

        d_from = self._dates[0].strftime('%Y-%m-%d')
        d_to   = self._dates[-1].strftime('%Y-%m-%d')
        wf     = self.worker_filter.currentData()

        # ── データ取得（通常 or スナップショット）──────────────────────────────
        if self._snapshot_mode and self._snapshot_data:
            snap        = self._snapshot_data
            all_scheds  = snap.get('schedules', [])
            all_workers = snap.get('workers', [])
            all_tasks   = snap.get('tasks', [])
            # 日付範囲・担当者でフィルタ
            sched_list  = [s for s in all_scheds
                           if d_from <= s['scheduled_date'] <= d_to
                           and (wf is None or s['worker_id'] == wf)]
            actual_list = []   # スナップショットモードでは実績を表示しない
        else:
            sched_list  = db.get_schedules(worker_id=wf, date_from=d_from, date_to=d_to)
            actual_list = db.get_actuals(worker_id=wf, date_from=d_from, date_to=d_to)
            all_workers = db.get_all_workers()
            all_tasks   = db.get_all_tasks()
            if wf:
                all_workers = [w for w in all_workers if w['id'] == wf]

        sched_lu  = {(s['worker_id'], s['task_id'], s['scheduled_date']): s
                     for s in sched_list}
        actual_lu = {(a['worker_id'], a['task_id'], a['actual_date']): a
                     for a in actual_list}
        _text_colors = db.get_task_text_colors()   # str(task_id) -> '#RRGGBB'

        # 表示行の (worker_id, task_id) ペアを収集（予定・実績どちらからも）
        pairs = set()
        for s in sched_list:
            pairs.add((s['worker_id'], s['task_id']))
        for a in actual_list:
            pairs.add((a['worker_id'], a['task_id']))
        pairs |= self._pinned_pairs
        # _row_order に登録済みのペアは期間外でも常に表示する
        pairs |= set(self._row_order)
        if wf:
            pairs = {(w, t) for w, t in pairs if w == wf}

        w_map = {w['id']: w for w in all_workers}
        t_map = {t['id']: t for t in all_tasks}

        # 既存の表示順を維持し、新規ペアを末尾（担当者名→作業名順）に追加
        existing = [(w, t) for w, t in self._row_order if (w, t) in pairs]
        existing_set = set(existing)
        new_pairs = sorted(
            [p for p in pairs if p not in existing_set],
            key=lambda x: (w_map.get(x[0], {}).get('name', ''),
                           t_map.get(x[1], {}).get('title', '')),
        )
        self._row_order = existing + new_pairs

        self._rows = [
            {'worker': w_map[wid], 'task': t_map[tid]}
            for wid, tid in self._row_order
            if wid in w_map and tid in t_map
        ]

        # ── 担当者境界行を計算 ──────────────────────────────────────────────────
        self._worker_boundary_rows = set()
        _prev_wid = None
        for _ri, _rw in enumerate(self._rows):
            _wid = _rw['worker']['id']
            if _prev_wid is not None and _wid != _prev_wid:
                self._worker_boundary_rows.add(_ri)
            _prev_wid = _wid

        # ── スナップショットモードの読み取り専用制御 ──────────────────────────
        is_snap = self._snapshot_mode and self._snapshot_data is not None
        if is_snap:
            self.table.setContextMenuPolicy(Qt.NoContextMenu)
            self.fixed_table.setContextMenuPolicy(Qt.NoContextMenu)
            self.table.viewport().setCursor(Qt.ArrowCursor)
        else:
            self.table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.fixed_table.setContextMenuPolicy(Qt.CustomContextMenu)

        # ── テーブル寸法設定 ────────────────────────────────────────────────
        n_rows  = len(self._rows)
        n_dates = len(self._dates)

        snap_date_str = (self._snapshot_data or {}).get('snapshot_date', '')

        # 固定テーブル（担当者・作業名・計）
        self.fixed_table.clearSpans()
        self.fixed_table.setRowCount(n_rows)
        self.fixed_table.setColumnCount(self.N_FIXED)
        hdrs = ['担当者', '作業名', '計(h)']
        if is_snap:
            hdrs[0] = f'担当者\n({snap_date_str}時点)'
        self.fixed_table.setHorizontalHeaderLabels(hdrs)
        for _ci, _cw in enumerate(self._fixed_col_widths):
            self.fixed_table.setColumnWidth(_ci, _cw)

        # 日付テーブル
        self.table.clearSpans()
        self.table.setRowCount(n_rows)
        self.table.setColumnCount(n_dates)

        if self._header_h < 28:
            date_hdrs = [f"{d.month}/{d.day}({_WEEKDAY[d.weekday()]})" for d in self._dates]
        else:
            date_hdrs = [f"{d.month}/{d.day}\n({_WEEKDAY[d.weekday()]})" for d in self._dates]
        self.table.setHorizontalHeaderLabels(date_hdrs)

        for _c, _d in enumerate(self._dates):
            self.table.setColumnWidth(_c, self._date_col_widths.get(_d.strftime('%Y-%m-%d'), self._default_date_col_w))
        for r in range(n_rows):
            _pair = (self._rows[r]['worker']['id'], self._rows[r]['task']['id'])
            _rh   = self._row_heights_by_pair.get(_pair, self._default_row_h)
            self.fixed_table.setRowHeight(r, _rh)
            self.table.setRowHeight(r, _rh)
            self.table.setVerticalHeaderItem(r, QTableWidgetItem(''))

        # 今日・祝日・土日のヘッダー色（毎回全属性を明示セットして前回の色が残らないようにする）
        for ci, d in enumerate(self._dates):
            h = self.table.horizontalHeaderItem(ci)
            if h is None:
                h = QTableWidgetItem()
                self.table.setHorizontalHeaderItem(ci, h)
            holiday = get_holiday(d)
            f = h.font()
            if d == today:
                h.setBackground(QColor('#E65100'))
                h.setForeground(QColor('#00E676'))
                f.setBold(True);  h.setFont(f)
                h.setToolTip(holiday if holiday else '')
            elif holiday:
                h.setBackground(QColor('#FFCDD2'))
                h.setForeground(QColor('#C62828'))
                f.setBold(True);  h.setFont(f)
                h.setToolTip(holiday)
            elif d.weekday() >= 5:
                h.setBackground(QColor('#BDBDBD'))
                h.setForeground(QColor('#C62828'))  # 土日も赤文字
                f.setBold(True);  h.setFont(f)
                h.setToolTip('')
            else:
                h.setBackground(QColor('#E3F2FD'))
                h.setForeground(QColor('#212121'))  # 平日は黒
                f.setBold(False); h.setFont(f)
                h.setToolTip('')

        # 担当者名セルのスパン（固定テーブル）
        for wid, grp in groupby(range(n_rows),
                                key=lambda r: self._rows[r]['worker']['id']):
            idxs  = list(grp)
            start = idxs[0]
            if len(idxs) > 1:
                self.fixed_table.setSpan(start, 0, len(idxs), 1)
            it = QTableWidgetItem(self._rows[start]['worker']['name'])
            it.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            it.setBackground(QColor('#E3F2FD'))
            f = it.font(); f.setBold(True); it.setFont(f)
            self.fixed_table.setItem(start, 0, it)

        # ── タスクカラー割当（同一作業=同色、隣接行は異なる色）────────────────
        _np = len(_TASK_PALETTE)
        _task_color: dict = {}   # task_id -> palette_idx
        _row_cidx:   list = []   # row index -> palette_idx
        for _rp, _rw in enumerate(self._rows):
            _tid = _rw['task']['id']
            if _tid in _task_color:
                _row_cidx.append(_task_color[_tid])
            else:
                _avoid = set()
                if _rp > 0 and self._rows[_rp - 1]['task']['id'] != _tid:
                    _avoid.add(_row_cidx[_rp - 1])
                for _c in range(_np):
                    if _c not in _avoid:
                        _task_color[_tid] = _c
                        _row_cidx.append(_c)
                        break
                else:
                    _task_color[_tid] = 0
                    _row_cidx.append(0)

        # 各行にセルを埋める
        for r, row in enumerate(self._rows):
            worker = row['worker']
            task   = row['task']

            row_bg = QColor('#E8F4FD') if r % 2 == 1 else QColor('#FFFFFF')

            # ── 土日祝日ギャップ検出（連続期間内の非稼働日を薄く表示）──────────
            row_scheds_sorted = sorted(
                [s for s in sched_list
                 if s['worker_id'] == worker['id'] and s['task_id'] == task['id']],
                key=lambda s: s['scheduled_date'],
            )
            gap_cell_lu = {}   # ds -> {'status': str, 'seg_idx': int}（ギャップセル用）
            seg_lu      = {}   # ds -> seg_idx（作業項目セグメント識別）
            if row_scheds_sorted:
                # 連続かつ同一 note+status を1セグメントとして番号付け
                _seg_idx = 0
                seg_lu[row_scheds_sorted[0]['scheduled_date']] = 0
                _grp = [row_scheds_sorted[0]]
                _span_groups = []
                for _s in row_scheds_sorted[1:]:
                    _d_prev = date.fromisoformat(_grp[-1]['scheduled_date'])
                    _d_curr = date.fromisoformat(_s['scheduled_date'])
                    _same_item = (
                        _s.get('note', '') == _grp[-1].get('note', '') and
                        _s.get('status', '') == _grp[-1].get('status', '')
                    )
                    if _nonwork_gap_only(_d_prev, _d_curr) and _same_item:
                        _grp.append(_s)
                    else:
                        _span_groups.append(_grp)
                        _grp = [_s]
                        _seg_idx += 1
                    seg_lu[_s['scheduled_date']] = _seg_idx
                _span_groups.append(_grp)
                for _grp in _span_groups:
                    _gstatus = _grp[0].get('status', 'planned')
                    _gseg    = seg_lu.get(_grp[0]['scheduled_date'], 0)
                    _gstart  = date.fromisoformat(_grp[0]['scheduled_date'])
                    _gend    = date.fromisoformat(_grp[-1]['scheduled_date'])
                    _cur = _gstart + timedelta(days=1)
                    while _cur < _gend:
                        _ds = _cur.strftime('%Y-%m-%d')
                        if not sched_lu.get((worker['id'], task['id'], _ds)):
                            gap_cell_lu[_ds] = {'status': _gstatus, 'seg_idx': _gseg}
                        _cur += timedelta(days=1)

            task_cidx = _row_cidx[r]

            ti = QTableWidgetItem(task['title'])
            ti.setFlags(ti.flags() & ~Qt.ItemIsEditable)
            ti.setBackground(row_bg)
            _tc = _text_colors.get(str(task['id']))
            if _tc:
                ti.setForeground(QColor(_tc))
            self.fixed_table.setItem(r, 1, ti)

            total_h = sum(
                sched_lu.get((worker['id'], task['id'], d.strftime('%Y-%m-%d')),
                             {}).get('scheduled_hours', 0)
                for d in self._dates
            )
            tot = QTableWidgetItem(f'{total_h:.1f}' if total_h else '')
            tot.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            tot.setFlags(tot.flags() & ~Qt.ItemIsEditable)
            tot.setBackground(row_bg)
            self.fixed_table.setItem(r, 2, tot)

            n_dates = len(self._dates)
            for ci, d in enumerate(self._dates):
                ds       = d.strftime('%Y-%m-%d')
                sched    = sched_lu.get((worker['id'], task['id'], ds))
                actual   = actual_lu.get((worker['id'], task['id'], ds))
                gap_span = gap_cell_lu.get(ds) if not sched else None

                # 連続スパン位置を判定（同一セグメント内のみ連結）
                if sched:
                    prev_ds   = self._dates[ci - 1].strftime('%Y-%m-%d') if ci > 0 else None
                    next_ds   = self._dates[ci + 1].strftime('%Y-%m-%d') if ci < n_dates - 1 else None
                    _cur_seg  = seg_lu.get(ds, -1)
                    has_prev  = bool(
                        prev_ds and
                        sched_lu.get((worker['id'], task['id'], prev_ds)) and
                        seg_lu.get(prev_ds, -2) == _cur_seg
                    )
                    has_next  = bool(
                        next_ds and
                        sched_lu.get((worker['id'], task['id'], next_ds)) and
                        seg_lu.get(next_ds, -2) == _cur_seg
                    )
                    if has_prev and has_next:
                        span_pos = 'middle'
                    elif has_prev:
                        span_pos = 'end'
                    elif has_next:
                        span_pos = 'start'
                    else:
                        span_pos = 'single'

                    # start/single セル：同一セグメント内の連続日数を計算
                    if span_pos in ('start', 'single'):
                        span_len = 1
                        j = ci + 1
                        while j < n_dates:
                            _jds = self._dates[j].strftime('%Y-%m-%d')
                            if (sched_lu.get((worker['id'], task['id'], _jds)) and
                                    seg_lu.get(_jds, -2) == _cur_seg):
                                span_len += 1
                                j += 1
                            else:
                                break
                    else:
                        span_len = 1
                else:
                    span_pos = 'single'
                    span_len = 1

                # セグメントごとにバー色をずらす（異なる作業項目が同行に並んでも区別できる）
                if sched:
                    _seg_i = seg_lu.get(ds, 0)
                elif gap_span:
                    _seg_i = gap_span.get('seg_idx', 0)
                else:
                    _seg_i = 0
                _cell_cidx = (task_cidx + _seg_i) % len(_TASK_PALETTE)

                item = QTableWidgetItem()
                holiday = get_holiday(d)
                item.setData(Qt.UserRole, {
                    'type':            'date_cell',
                    'worker':          worker,
                    'task':            task,
                    'date':            ds,
                    'date_obj':        d,
                    'schedule':        sched,
                    'actual':          actual,
                    'span_pos':        span_pos,
                    'span_len':        span_len,
                    'holiday':         holiday,
                    'task_color_idx':  _cell_cidx,
                    'span_gap':        bool(gap_span),
                    'gap_status':      gap_span['status'] if gap_span else None,
                    'text_color':      _text_colors.get(str(task['id'])),
                    'worker_boundary': r in self._worker_boundary_rows,
                })
                tip_parts = []
                if holiday:
                    tip_parts.append(holiday)
                if actual and actual.get('note'):
                    tip_parts.append(actual['note'])
                if tip_parts:
                    item.setToolTip('　'.join(tip_parts))
                self.table.setItem(r, ci, item)

        # テキストが1セル幅を超える場合、右隣の空きセルに top_half_clear マーカーを設定
        # （paint() がそのセルの上半分を塗らず、はみ出しテキストが見えるようにする）
        _fov  = QFont("Yu Gothic UI"); _fov.setPointSize(7)
        _fmov = QFontMetrics(_fov)
        _nd   = len(self._dates)
        for _r in range(n_rows):
            for _ci in range(_nd):
                _itm = self.table.item(_r, _ci)
                if not _itm:
                    continue
                _d = _itm.data(Qt.UserRole)
                if not (_d and _d.get('schedule') and _d.get('span_pos') in ('single', 'start')):
                    continue
                _sp = _d.get('span_len', 1)
                _to = _d.get('task', {})
                _sc = _d.get('schedule', {})
                _tx = _sc.get('note', '') or _to.get('category', '') or _to.get('title', '')
                _bw = sum(self.table.columnWidth(_ci + j) for j in range(_sp))
                _need = _fmov.horizontalAdvance(_tx) + 10
                if _need <= _bw:
                    continue
                _ex, _col = 0, _ci + _sp
                while _col < _nd and _ex + _bw < _need:
                    _ai = self.table.item(_r, _col)
                    if not _ai:
                        break
                    _ad = _ai.data(Qt.UserRole)
                    if not _ad or _ad.get('schedule'):
                        break
                    _ad['top_half_clear'] = True
                    _ai.setData(Qt.UserRole, _ad)
                    _ex += self.table.columnWidth(_col)
                    _col += 1

        self._building_table = False
        self._update_fixed_width()
        QTimer.singleShot(0, self._sync_header_height)

    # ── ヘッダー高さ ─────────────────────────────────────────────────────────

    def _sync_header_height(self):
        """保存済みのヘッダー高さを適用する。初回は自然高さの半分をデフォルトとする。"""
        saved = db.get_setting('gantt_header_height', '')
        if saved and saved.lstrip('-').isdigit() and int(saved) >= 16:
            h = int(saved)
        else:
            natural = self.table.horizontalHeader().height()
            h = max(16, natural // 2) if natural > 0 else 20
            db.set_setting('gantt_header_height', str(h))
        self._apply_header_height(h)

    def _on_header_height_changed(self, h: int):
        db.set_setting('gantt_header_height', str(h))
        prev = self._header_h
        self._header_h = h
        if (prev < 28) != (h < 28):
            # 1行⇔2行の境界をまたいだ場合はヘッダーテキストを再生成
            self._build_table()
            return
        self._apply_header_height(h)

    def _apply_header_height(self, h: int):
        self._header_h = h
        self.fixed_table.horizontalHeader().setFixedHeight(h)
        self.table.horizontalHeader().setFixedHeight(h)
        self.header_height_spin.blockSignals(True)
        self.header_height_spin.setValue(h)
        self.header_height_spin.blockSignals(False)

    # ── 列幅・行高さ リサイズ ─────────────────────────────────────────────────

    def _on_fixed_col_resized(self, idx: int, old: int, new: int):
        if self._building_table:
            return
        if idx < len(self._fixed_col_widths):
            self._fixed_col_widths[idx] = new
        self._update_fixed_width()
        self._layout_save_timer.start()

    def _update_fixed_width(self):
        total = sum(self._fixed_col_widths) + 4
        self.fixed_table.setFixedWidth(total)

    def _on_date_col_resized(self, idx: int, old: int, new: int):
        if self._building_table:
            return
        if idx < len(self._dates):
            self._date_col_widths[self._dates[idx].strftime('%Y-%m-%d')] = new
        self._layout_save_timer.start()

    def _on_row_resized(self, idx: int, old: int, new: int):
        if self._building_table:
            return
        if idx < len(self._rows):
            pair = (self._rows[idx]['worker']['id'], self._rows[idx]['task']['id'])
            self._row_heights_by_pair[pair] = new
        self.fixed_table.setRowHeight(idx, new)
        self._layout_save_timer.start()

    # ── レイアウト保存・復元 ──────────────────────────────────────────────────

    def _load_layout_settings(self):
        """起動時に保存済みのレイアウト設定を復元する。"""
        try:
            v = db.get_setting('gantt_row_order', '')
            if v:
                self._row_order = [tuple(p) for p in json.loads(v)]
        except Exception:
            pass
        try:
            v = db.get_setting('gantt_pinned_pairs', '')
            if v:
                self._pinned_pairs = {tuple(p) for p in json.loads(v)}
        except Exception:
            pass
        try:
            v = db.get_setting('gantt_fixed_col_widths', '')
            if v:
                loaded = json.loads(v)
                if isinstance(loaded, list) and len(loaded) == self.N_FIXED:
                    self._fixed_col_widths = loaded
        except Exception:
            pass
        try:
            v = db.get_setting('gantt_date_col_widths', '')
            if v:
                self._date_col_widths = json.loads(v)
        except Exception:
            pass
        try:
            v = db.get_setting('gantt_row_heights', '')
            if v:
                self._row_heights_by_pair = {
                    (int(k.split('_')[0]), int(k.split('_')[1])): int(h)
                    for k, h in json.loads(v).items()
                }
        except Exception:
            pass

    # ── zoom ─────────────────────────────────────────────────────────────────

    def _apply_zoom(self) -> None:
        font = self._zoom_font()
        self.fixed_table.setFont(font)
        self.table.setFont(font)
        fm = QFontMetrics(font)
        self._default_row_h = max(fm.height() * 3 + 4, 40)
        self.table.verticalHeader().setDefaultSectionSize(self._default_row_h)
        self._update_zoom_label()
        if self._dates:
            self._build_table()

    # ── layout persistence ───────────────────────────────────────────────────

    def _save_all_layout(self):
        """列幅・行高さをDBに保存する（デバウンスタイマーから呼ばれる）。"""
        db.set_setting('gantt_fixed_col_widths', json.dumps(self._fixed_col_widths))
        db.set_setting('gantt_date_col_widths', json.dumps(self._date_col_widths))
        heights = {f'{w}_{t}': h for (w, t), h in self._row_heights_by_pair.items()}
        db.set_setting('gantt_row_heights', json.dumps(heights))

    def _save_row_order(self):
        """行順とピン留めをDBに即時保存する。"""
        db.set_setting('gantt_row_order', json.dumps(self._row_order))
        db.set_setting('gantt_pinned_pairs', json.dumps(list(self._pinned_pairs)))

    def _apply_schedule_spans(self, n_rows: int, n_cols: int):
        """連続した予定セルを setSpan で結合し、最初のセルにまとめて記録する"""
        for r in range(n_rows):
            c = 0
            while c < n_cols:
                item = self.table.item(r, c)
                if not item:
                    c += 1; continue
                data = item.data(Qt.UserRole)
                if not (data and data.get('schedule')):
                    c += 1; continue

                # 連続ブロックの末端を探す
                span_start = c
                span_dates   = [data['date']]
                span_scheds  = [data['schedule']]
                span_actuals = [data.get('actual')]

                end_c = c
                while end_c + 1 < n_cols:
                    nxt = self.table.item(r, end_c + 1)
                    if not nxt:
                        break
                    nd = nxt.data(Qt.UserRole)
                    if not (nd and nd.get('schedule')):
                        break
                    end_c += 1
                    span_dates.append(nd['date'])
                    span_scheds.append(nd['schedule'])
                    span_actuals.append(nd.get('actual'))

                span_len = end_c - span_start + 1
                if span_len > 1:
                    self.table.setSpan(r, span_start, 1, span_len)
                    # 最初のセルにスパン情報を追記
                    first = self.table.item(r, span_start)
                    fd = first.data(Qt.UserRole)
                    fd['span_schedules'] = span_scheds
                    fd['span_actuals']   = span_actuals
                    fd['span_dates']     = span_dates
                    first.setData(Qt.UserRole, fd)

                c = end_c + 1   # スパン末尾の次へ

    # ── セルデータ取得 ────────────────────────────────────────────────────────

    def _cell_data(self, row: int, col: int):
        it = self.table.item(row, col)
        return it.data(Qt.UserRole) if it else None

    # ── ドラッグ → 複数日ダイアログ ──────────────────────────────────────────

    def _open_range_dialog(self, row: int, c0: int, c1: int):
        if row >= len(self._rows):
            return
        if not db.get_all_workers() or not db.get_all_tasks():
            QMessageBox.warning(self, "マスタ未登録",
                                "担当者・作業をマスタ管理タブで先に登録してください")
            return

        r_data = self._rows[row]
        start  = self._dates[c0].strftime('%Y-%m-%d')
        end    = self._dates[c1].strftime('%Y-%m-%d')

        dlg = GanttScheduleDialog(
            self,
            worker=r_data['worker'], task=r_data['task'],
            start_date=start, end_date=end,
        )
        if dlg.exec_() == QDialog.Accepted:
            db.begin_action()
            for sd in dlg.get_schedules():
                db.add_schedule(**sd)
            db.end_action()
            self.refresh()

    # ── ダブルクリック → 単日追加 / 編集 ────────────────────────────────────

    def _get_span_dates(self, worker_id: int, task_id: int,
                        clicked: date) -> list:
        """クリックした日を含む予定グループの実際の日付リストを返す。
        14日以内のギャップは同一グループとみなす（週末・祝日を跨ぐ予定に対応）。"""
        scheds = db.get_schedules(
            worker_id=worker_id,
            date_from=(clicked - timedelta(days=365)).strftime('%Y-%m-%d'),
            date_to=(clicked + timedelta(days=365)).strftime('%Y-%m-%d'),
        )
        all_dates = sorted({
            date.fromisoformat(s['scheduled_date'])
            for s in scheds if s['task_id'] == task_id
        })
        if not all_dates:
            return [clicked]
        MAX_GAP = 14
        groups, cur_group = [], [all_dates[0]]
        for d in all_dates[1:]:
            if (d - cur_group[-1]).days <= MAX_GAP:
                cur_group.append(d)
            else:
                groups.append(cur_group)
                cur_group = [d]
        groups.append(cur_group)
        for group in groups:
            if clicked in group:
                return group
        return [clicked]

    def _edit_or_add_schedule(self, data: dict):
        if not db.get_all_workers() or not db.get_all_tasks():
            QMessageBox.warning(self, "マスタ未登録",
                                "担当者・作業をマスタ管理タブで先に登録してください")
            return

        sched  = data.get('schedule')
        worker = data['worker']
        task   = data['task']

        if sched:
            # クリックした日を含むグループ（週末・祝日ギャップ込み）の全日付を取得
            span_dates = self._get_span_dates(worker['id'], task['id'], data['date_obj'])
            dlg = GanttScheduleDialog(
                self,
                worker=worker, task=task,
                start_date=span_dates[0].strftime('%Y-%m-%d'),
                initial_dates=span_dates,
                hours_per_day=sched.get('scheduled_hours', 8.0),
                status=sched.get('status', 'planned'),
                note=sched.get('note', ''),
                is_edit=True,
            )
            if dlg.exec_() == QDialog.Accepted:
                old_scheds = db.get_schedules(
                    worker_id=worker['id'],
                    date_from=span_dates[0].strftime('%Y-%m-%d'),
                    date_to=span_dates[-1].strftime('%Y-%m-%d'),
                )
                db.begin_action()
                for s in old_scheds:
                    if s['task_id'] == task['id']:
                        db.delete_schedule(s['id'])
                for sd in dlg.get_schedules():
                    db.add_schedule(**sd)
                db.end_action()
                self.refresh()
        else:
            dlg = GanttScheduleDialog(
                self,
                worker=worker, task=task,
                start_date=data['date'], end_date=data['date'],
            )
            if dlg.exec_() == QDialog.Accepted:
                db.begin_action()
                for sd in dlg.get_schedules():
                    db.add_schedule(**sd)
                db.end_action()
                self.refresh()

    def _edit_span(self, data: dict):
        """スパンバー（複数日）を一括編集"""
        span_scheds = data['span_schedules']
        s0 = span_scheds[0]
        s1 = span_scheds[-1]

        dlg = GanttScheduleDialog(
            self,
            worker=data['worker'], task=data['task'],
            start_date=s0['scheduled_date'],
            end_date=s1['scheduled_date'],
            hours_per_day=s0.get('scheduled_hours', 8.0),
            status=s0.get('status', 'planned'),
            note=s0.get('note', ''),
            is_edit=True,
        )
        if dlg.exec_() == QDialog.Accepted:
            db.begin_action()
            for s in span_scheds:
                db.delete_schedule(s['id'])
            for sd in dlg.get_schedules():
                db.add_schedule(**sd)
            db.end_action()
            self.refresh()

    def _delete_span(self, data: dict):
        """単日予定を削除"""
        sched = data.get('schedule')
        if not sched:
            return

        msg = (f"「{data['worker']['name']} / {data['task']['title']}」\n"
               f"{sched['scheduled_date']} の予定を削除しますか？")

        if QMessageBox.question(self, "削除確認", msg,
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            db.delete_schedule(sched['id'])
            self.refresh()

    # ── 右クリック コンテキストメニュー ──────────────────────────────────────

    def _on_fixed_context_menu(self, pos: QPoint):
        row = self.fixed_table.rowAt(pos.y())
        if row < 0 or row >= len(self._rows):
            return
        r_data = self._rows[row]
        task   = r_data['task']
        colors = db.get_task_text_colors()
        cur_hex = colors.get(str(task['id']), '')

        menu = QMenu(self)

        color_lbl = f"テキストの色を変更（現在: {cur_hex}）" if cur_hex else "テキストの色を設定"
        menu.addAction(color_lbl).triggered.connect(
            lambda: self._change_text_color(r_data)
        )
        if cur_hex:
            menu.addAction("テキストの色をリセット（デフォルトに戻す）").triggered.connect(
                lambda: self._reset_text_color(r_data)
            )
        menu.addSeparator()
        menu.addAction(
            f"「{r_data['worker']['name']} / {r_data['task']['title']}」 の行を削除"
        ).triggered.connect(lambda: self._delete_row(r_data))
        menu.exec_(self.fixed_table.viewport().mapToGlobal(pos))

    def _change_text_color(self, r_data: dict):
        task = r_data['task']
        cur  = db.get_task_text_colors().get(str(task['id']), '#1565C0')
        color = QColorDialog.getColor(
            QColor(cur), self, f"「{task['title']}」のテキスト色を選択"
        )
        if color.isValid():
            db.set_task_text_color(task['id'], color.name())
            self._build_table()

    def _reset_text_color(self, r_data: dict):
        db.set_task_text_color(r_data['task']['id'], '')
        self._build_table()

    def _on_context_menu(self, pos: QPoint):
        it = self.table.itemAt(pos)
        if not it:
            return

        row = it.row()
        col = it.column()

        # ── 日付列 ────────────────────────────────────────────────────────────
        data = self._cell_data(row, col)
        if not data or data.get('type') != 'date_cell':
            return

        sched  = data.get('schedule')
        actual = data.get('actual')
        menu   = QMenu(self)

        if sched:
            menu.addAction("予定を編集").triggered.connect(
                lambda: self._edit_or_add_schedule(data))
            menu.addAction("予定を削除").triggered.connect(
                lambda: self._delete_span(data))
        else:
            menu.addAction("予定を追加").triggered.connect(
                lambda: self._edit_or_add_schedule(data))

        menu.addSeparator()

        if actual:
            menu.addAction("実績を編集").triggered.connect(
                lambda: self._edit_actual(data))
            menu.addAction("実績を削除").triggered.connect(
                lambda: self._delete_actual(actual))
        else:
            menu.addAction("実績を入力").triggered.connect(
                lambda: self._add_actual(data))

        menu.exec_(self.table.viewport().mapToGlobal(pos))

    # ── 行削除 ────────────────────────────────────────────────────────────────

    def _delete_row(self, r_data: dict):
        worker = r_data['worker']
        task   = r_data['task']
        wid, tid = worker['id'], task['id']

        d_from = self._dates[0].strftime('%Y-%m-%d') if self._dates else None
        d_to   = self._dates[-1].strftime('%Y-%m-%d') if self._dates else None

        scheds   = [s for s in db.get_schedules(worker_id=wid, date_from=d_from, date_to=d_to)
                    if s['task_id'] == tid]
        actuals  = [a for a in db.get_actuals(worker_id=wid, date_from=d_from, date_to=d_to)
                    if a['task_id'] == tid]

        parts = []
        if scheds:
            parts.append(f"予定 {len(scheds)} 件")
        if actuals:
            parts.append(f"実績 {len(actuals)} 件")

        msg = f"「{worker['name']} / {task['title']}」 の行を削除します。\n"
        if parts:
            msg += "（" + "・".join(parts) + " も削除されます）\n"
        msg += "\nよろしいですか？"

        if QMessageBox.question(self, "行の削除", msg,
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        db.begin_action()
        for s in scheds:
            db.delete_schedule(s['id'])
        for a in actuals:
            db.delete_actual(a['id'])
        db.end_action()
        self._pinned_pairs.discard((wid, tid))
        self._row_order = [(w, t) for w, t in self._row_order if (w, t) != (wid, tid)]
        self._save_row_order()
        self.refresh()
        if actuals:
            self.actuals_changed.emit()

    # ── 実績 CRUD ─────────────────────────────────────────────────────────────

    def _add_actual(self, data: dict):
        schedule = data.get('schedule') or {}
        pre = {
            'worker_id':  data['worker']['id'],
            'task_id':    data['task']['id'],
            'actual_date': data['date'],
            'note':       schedule.get('note', ''),   # 作業項目をデフォルトに
        }
        dlg = ActualDialog(self, schedule=pre)
        if dlg.exec_() == QDialog.Accepted:
            d   = dlg.get_data()
            sid = (data.get('schedule') or {}).get('id')
            db.add_actual(schedule_id=sid, **d)
            self.refresh()
            self.actuals_changed.emit()

    def _edit_actual(self, data: dict):
        dlg = ActualDialog(self, actual=data.get('actual'))
        if dlg.exec_() == QDialog.Accepted:
            db.update_actual(data['actual']['id'], **dlg.get_data())
            self.refresh()
            self.actuals_changed.emit()

    def _delete_actual(self, actual: dict):
        if QMessageBox.question(
            self, "削除確認",
            f"「{actual['worker_name']} / {actual['task_title']} / {actual['actual_date']}」"
            "の実績を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            db.delete_actual(actual['id'])
            self.refresh()
            self.actuals_changed.emit()

    # ── 行追加（ピン留め） ────────────────────────────────────────────────────

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
        for w in workers: w_combo.addItem(w['name'], w['id'])
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
                self._save_row_order()
                self._build_table()
