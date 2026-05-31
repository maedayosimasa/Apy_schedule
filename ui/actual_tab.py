from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QComboBox, QDateEdit, QPushButton, QHeaderView,
    QMessageBox, QDialog,
)
from PyQt5.QtCore import QDate, Qt, pyqtSignal, QSortFilterProxyModel
import database as db
from models import ActualTableModel
from ui.dialogs import ActualDialog
from ui.zoom_mixin import ZoomMixin, ZoomableTableView


class _ActualSortProxy(QSortFilterProxyModel):
    """列ヘッダークリックでソートできるプロキシモデル。
    ID・実績時間列は数値として比較する。"""
    _NUMERIC_COLS = {0, 5}   # ID, 実績時間(h)

    def lessThan(self, left, right):
        col = left.column()
        lv = left.data(Qt.DisplayRole) or ''
        rv = right.data(Qt.DisplayRole) or ''
        if col in self._NUMERIC_COLS:
            try:
                return float(lv) < float(rv)
            except ValueError:
                pass
        return lv < rv


class ActualTab(QWidget, ZoomMixin):
    actuals_changed = pyqtSignal()   # 実績の追加/編集/削除時に emit

    def __init__(self):
        super().__init__()
        self._init_zoom("zoom_actual")
        self._setup_ui()
        self.refresh()
        self._apply_zoom()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── filter bar ──────────────────────────────────────────────────────
        group = QGroupBox("絞り込み")
        fl = QHBoxLayout(group)

        fl.addWidget(QLabel("担当者:"))
        self.worker_filter = QComboBox()
        self.worker_filter.setMinimumWidth(120)
        fl.addWidget(self.worker_filter)

        fl.addWidget(QLabel("  期間:"))
        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDate(QDate.currentDate().addDays(-7))
        fl.addWidget(self.from_date)

        fl.addWidget(QLabel("〜"))
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDate(QDate.currentDate().addDays(30))
        fl.addWidget(self.to_date)

        search_btn = QPushButton("検索")
        search_btn.clicked.connect(self.refresh)
        fl.addWidget(search_btn)
        self._make_zoom_controls(fl)
        fl.addStretch()
        layout.addWidget(group)

        # ── table ────────────────────────────────────────────────────────────
        self.model = ActualTableModel()
        self.proxy = _ActualSortProxy()
        self.proxy.setSourceModel(self.model)

        self.table = ZoomableTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(ZoomableTableView.SelectRows)
        self.table.setSelectionMode(ZoomableTableView.SingleSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)   # 全列を基本に内容幅
        hh.setSectionResizeMode(3, QHeaderView.Stretch)         # 実施内容列だけ伸縮
        hh.setSortIndicatorShown(True)
        self.table.setColumnHidden(0, True)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        # デフォルトは実績日の昇順
        self.table.sortByColumn(4, Qt.AscendingOrder)
        layout.addWidget(self.table)
        self._register_zoom_table(self.table)

        self.summary_label = QLabel()
        layout.addWidget(self.summary_label)

        # ── buttons ──────────────────────────────────────────────────────────
        bl = QHBoxLayout()
        for label, slot in [
            ("追加", self.add_actual),
            ("編集", self.edit_actual),
            ("削除", self.delete_actual),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            bl.addWidget(btn)
        bl.addStretch()
        layout.addLayout(bl)

    # ── public ───────────────────────────────────────────────────────────────

    def reload_workers(self):
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

    def refresh(self):
        self.reload_workers()
        worker_id = self.worker_filter.currentData()
        date_from = self.from_date.date().toString("yyyy-MM-dd")
        date_to   = self.to_date.date().toString("yyyy-MM-dd")
        data = db.get_actuals(worker_id=worker_id, date_from=date_from, date_to=date_to)
        self.model.refresh(data)
        self.table.resizeRowsToContents()
        total = sum(r["actual_hours"] for r in data)
        self.summary_label.setText(f"件数: {len(data)} 件   合計実績時間: {total:.1f} h")

    # ── private ──────────────────────────────────────────────────────────────

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "未選択", "行を選択してください")
            return None
        src_idx = self.proxy.mapToSource(rows[0])
        return self.model.get_row_data(src_idx.row())

    def add_actual(self):
        dlg = ActualDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            db.add_actual(**dlg.get_data())
            self.refresh()
            self.actuals_changed.emit()

    def edit_actual(self):
        row = self._selected()
        if not row:
            return
        dlg = ActualDialog(self, actual=row)
        if dlg.exec_() == QDialog.Accepted:
            db.update_actual(row["id"], **dlg.get_data())
            self.refresh()
            self.actuals_changed.emit()

    def delete_actual(self):
        row = self._selected()
        if not row:
            return
        if QMessageBox.question(
            self, "削除確認",
            f"「{row['worker_name']} / {row['task_title']} / {row['actual_date']}」を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            db.delete_actual(row["id"])
            self.refresh()
            self.actuals_changed.emit()

    # ── zoom ─────────────────────────────────────────────────────────────────

    def _apply_zoom(self) -> None:
        self.table.setFont(self._zoom_font())
        self.table.resizeRowsToContents()
        self._update_zoom_label()
