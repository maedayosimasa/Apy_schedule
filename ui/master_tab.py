from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGroupBox,
    QListWidget, QPushButton, QMessageBox, QDialog, QLabel,
)
import database as db
from ui.dialogs import WorkerDialog, TaskDialog


class MasterTab(QWidget):
    def __init__(self):
        super().__init__()
        self._workers = []
        self._tasks   = []
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        outer = QVBoxLayout(self)

        master_row = QHBoxLayout()

        # ── workers ──────────────────────────────────────────────────────────
        wg = QGroupBox("担当者マスタ")
        wl = QVBoxLayout(wg)
        self.workers_list = QListWidget()
        self.workers_list.setAlternatingRowColors(True)
        wl.addWidget(self.workers_list)
        wbl = QHBoxLayout()
        for label, slot in [("追加", self._add_worker),
                             ("編集", self._edit_worker),
                             ("削除", self._del_worker)]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            wbl.addWidget(btn)
        wl.addLayout(wbl)
        master_row.addWidget(wg)

        # ── tasks ─────────────────────────────────────────────────────────────
        tg = QGroupBox("作業マスタ")
        tl = QVBoxLayout(tg)
        self.tasks_list = QListWidget()
        self.tasks_list.setAlternatingRowColors(True)
        tl.addWidget(self.tasks_list)
        tbl = QHBoxLayout()
        for label, slot in [("追加", self._add_task),
                             ("編集", self._edit_task),
                             ("削除", self._del_task)]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            tbl.addWidget(btn)
        tl.addLayout(tbl)
        master_row.addWidget(tg)

        outer.addLayout(master_row)

        # ── リセットボタン ─────────────────────────────────────────────────────
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        reset_btn = QPushButton("全データをリセット（初期化）")
        reset_btn.setStyleSheet(
            "QPushButton { background-color: #C62828; color: white;"
            " border-radius: 4px; padding: 6px 18px; }"
            "QPushButton:hover { background-color: #B71C1C; }"
            "QPushButton:pressed { background-color: #7F0000; }"
        )
        reset_btn.clicked.connect(self._reset_all)
        reset_row.addWidget(reset_btn)
        outer.addLayout(reset_row)

    # ── public ───────────────────────────────────────────────────────────────

    def refresh(self):
        self._workers = db.get_all_workers()
        self.workers_list.clear()
        for w in self._workers:
            dept = f"  [{w['department']}]" if w.get("department") else ""
            self.workers_list.addItem(f"{w['name']}{dept}")

        self._tasks = db.get_all_tasks()
        self.tasks_list.clear()
        for t in self._tasks:
            cat = f"  [{t['category']}]" if t.get("category") else ""
            self.tasks_list.addItem(f"{t['title']}{cat}")

    # ── workers actions ──────────────────────────────────────────────────────

    def _add_worker(self):
        dlg = WorkerDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.get_data()
            db.add_worker(d["name"], d["department"])
            self.refresh()

    def _edit_worker(self):
        row = self.workers_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "未選択", "担当者を選択してください")
            return
        dlg = WorkerDialog(self, worker=self._workers[row])
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.get_data()
            db.update_worker(self._workers[row]["id"], d["name"], d["department"])
            self.refresh()

    def _del_worker(self):
        row = self.workers_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "未選択", "担当者を選択してください")
            return
        w = self._workers[row]
        if QMessageBox.question(
            self, "削除確認",
            f"「{w['name']}」を削除しますか？\n関連する予定・実績も削除されます。",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            db.delete_worker(w["id"])
            self.refresh()

    # ── tasks actions ─────────────────────────────────────────────────────────

    def _add_task(self):
        dlg = TaskDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.get_data()
            db.add_task(d["title"], d["description"], d["category"])
            self.refresh()

    def _edit_task(self):
        row = self.tasks_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "未選択", "作業を選択してください")
            return
        dlg = TaskDialog(self, task=self._tasks[row])
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.get_data()
            db.update_task(self._tasks[row]["id"], d["title"], d["description"], d["category"])
            self.refresh()

    def _del_task(self):
        row = self.tasks_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "未選択", "作業を選択してください")
            return
        t = self._tasks[row]
        if QMessageBox.question(
            self, "削除確認",
            f"「{t['title']}」を削除しますか？\n関連する予定・実績も削除されます。",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            db.delete_task(t["id"])
            self.refresh()

    # ── リセット ──────────────────────────────────────────────────────────────

    def _reset_all(self):
        ans = QMessageBox.warning(
            self, "全データのリセット",
            "担当者・作業・予定・実績・変更履歴の\n"
            "すべてのデータを削除してデータベースを初期化します。\n\n"
            "この操作は取り消せません。実行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return

        # 二重確認
        ans2 = QMessageBox.critical(
            self, "最終確認",
            "本当にすべてのデータを削除しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans2 != QMessageBox.Yes:
            return

        db.reset_db()
        self.refresh()
        QMessageBox.information(self, "完了", "データベースを初期状態にリセットしました。")
