"""全ユーザーのDBをマージして表示する読み取り専用の共有スケジュールタブ。"""
from __future__ import annotations
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QComboBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

import database as db
from sync import presence
from sync.cache import shared_cache

_STATUS_LABELS = {
    "planned":     "予定",
    "in_progress": "進行中",
    "done":        "完了",
    "cancelled":   "中止",
}

_STATUS_COLORS = {
    "planned":     QColor("#E3F2FD"),
    "in_progress": QColor("#FFF9C4"),
    "done":        QColor("#E8F5E9"),
    "cancelled":   QColor("#F5F5F5"),
}

_COLUMNS = [
    ("ユーザー",     "_source"),
    ("担当者",       "worker_name"),
    ("作業",         "task_title"),
    ("日付",         "scheduled_date"),
    ("予定時間(h)",  "scheduled_hours"),
    ("ステータス",   "status"),
    ("メモ",         "note"),
]


class SharedTab(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── ツールバー行 ──────────────────────────────────────────────────────
        toolbar = QHBoxLayout()

        self._summary_label = QLabel("チーム共有スケジュール（読み取り専用）")
        toolbar.addWidget(self._summary_label)
        toolbar.addStretch()

        toolbar.addWidget(QLabel("ユーザー絞り込み:"))
        self._filter_combo = QComboBox()
        self._filter_combo.setFixedWidth(140)
        self._filter_combo.addItem("すべて")
        self._filter_combo.currentTextChanged.connect(self._apply_filter)
        toolbar.addWidget(self._filter_combo)

        self._last_updated = QLabel("")
        self._last_updated.setStyleSheet("color:#888; font-size:9px;")
        toolbar.addWidget(self._last_updated)

        refresh_btn = QPushButton("⟳ 更新")
        refresh_btn.setFixedWidth(76)
        refresh_btn.setToolTip("全ユーザーのDBを再読み込みします")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        layout.addLayout(toolbar)

        # ── テーブル ──────────────────────────────────────────────────────────
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([c[0] for c in _COLUMNS])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(False)
        self._table.setWordWrap(False)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setStretchLastSection(True)
        self._table.verticalHeader().setDefaultSectionSize(22)
        layout.addWidget(self._table)

        self._all_rows: list[dict] = []

    # ── 公開メソッド ──────────────────────────────────────────────────────────

    def refresh(self):
        """キャッシュからデータを再読み込みしてテーブルを更新する。"""
        if db.get_shared_folder() is None:
            self._summary_label.setText(
                "共有フォルダが未設定です。⚙ 設定から「共有フォルダ」と「ユーザー名」を指定してください。"
            )
            self._table.setRowCount(0)
            return

        schedules = shared_cache.get_all_schedules()
        schedules.sort(key=lambda s: (
            s.get("scheduled_date", ""),
            s.get("_source", ""),
            s.get("worker_name", ""),
        ))
        self._all_rows = schedules

        # ユーザー絞り込みコンボ更新
        sources  = sorted({s["_source"] for s in schedules})
        current  = self._filter_combo.currentText()
        self._filter_combo.blockSignals(True)
        self._filter_combo.clear()
        self._filter_combo.addItem("すべて")
        for src in sources:
            self._filter_combo.addItem(src)
        idx = self._filter_combo.findText(current)
        self._filter_combo.setCurrentIndex(max(0, idx))
        self._filter_combo.blockSignals(False)

        self._apply_filter()

        now = datetime.now().strftime("%H:%M:%S")
        self._last_updated.setText(f"更新: {now}")

    # ── 内部 ─────────────────────────────────────────────────────────────────

    def _apply_filter(self):
        selected = self._filter_combo.currentText()
        rows = self._all_rows if selected == "すべて" else [
            r for r in self._all_rows if r["_source"] == selected
        ]
        self._fill_table(rows)

        user_count = len({r["_source"] for r in rows})
        text = f"チーム共有スケジュール（読み取り専用）　{user_count} ユーザー / {len(rows)} 件"
        folder = db.get_shared_folder()
        if folder is not None and folder.exists():
            online = sorted(presence.active_users(folder))
            if online:
                text += "　│　🟢 使用中: " + "、".join(online)
        self._summary_label.setText(text)

    def _fill_table(self, rows: list[dict]):
        own = db.DB_PATH.stem if db.is_db_in_shared_folder() else None
        self._table.setRowCount(0)
        for row_data in rows:
            row = self._table.rowCount()
            self._table.insertRow(row)
            status = str(row_data.get("status", ""))
            bg     = _STATUS_COLORS.get(status, QColor("#FFFFFF"))

            for col, (_, key) in enumerate(_COLUMNS):
                val = row_data.get(key, "")
                if key == "_source":
                    val = f"{val}（{'メイン' if val == own else '参照'}）"
                if key == "status":
                    val = _STATUS_LABELS.get(str(val), str(val))
                text = str(val) if val is not None else ""
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(bg)
                self._table.setItem(row, col, item)
