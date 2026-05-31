from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QComboBox, QDateEdit, QPushButton, QTableView, QHeaderView,
    QMessageBox, QDialog,
)
from PyQt5.QtCore import QDate
import database as db
from models import ScheduleTableModel
from ui.dialogs import ScheduleDialog, ActualDialog


class ScheduleTab(QWidget):
    def __init__(self):
        super().__init__()
        self._setup_ui()
        self.refresh()

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
        fl.addStretch()
        layout.addWidget(group)

        # ── table ────────────────────────────────────────────────────────────
        self.model = ScheduleTableModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setColumnHidden(0, True)
        self.table.setSortingEnabled(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self.summary_label = QLabel()
        layout.addWidget(self.summary_label)

        # ── buttons ──────────────────────────────────────────────────────────
        bl = QHBoxLayout()
        for label, slot in [
            ("追加",     self.add_schedule),
            ("編集",     self.edit_schedule),
            ("削除",     self.delete_schedule),
            ("実績入力", self.enter_actual),
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
        data = db.get_schedules(worker_id=worker_id, date_from=date_from, date_to=date_to)
        self.model.refresh(data)
        total = sum(r["scheduled_hours"] for r in data)
        self.summary_label.setText(f"件数: {len(data)} 件   合計予定時間: {total:.1f} h")

    # ── private ──────────────────────────────────────────────────────────────

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "未選択", "行を選択してください")
            return None
        return self.model.get_row_data(rows[0].row())

    def add_schedule(self):
        dlg = ScheduleDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            db.add_schedule(**dlg.get_data())
            self.refresh()

    def edit_schedule(self):
        row = self._selected()
        if not row:
            return
        dlg = ScheduleDialog(self, schedule=row)
        if dlg.exec_() == QDialog.Accepted:
            db.update_schedule(row["id"], **dlg.get_data())
            self.refresh()

    def delete_schedule(self):
        row = self._selected()
        if not row:
            return
        if QMessageBox.question(
            self, "削除確認",
            f"「{row['worker_name']} / {row['task_title']} / {row['scheduled_date']}」を削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            db.delete_schedule(row["id"])
            self.refresh()

    def enter_actual(self):
        row = self._selected()
        if not row:
            return
        dlg = ActualDialog(self, schedule=row)
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.get_data()
            db.add_actual(schedule_id=row["id"], **d)
            QMessageBox.information(self, "登録完了", "実績を登録しました")
