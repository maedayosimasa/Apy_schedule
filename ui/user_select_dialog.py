"""起動時のユーザー選択ダイアログ。

共有フォルダ内のユーザーDB一覧を表示し、選んだユーザーをメイン（編集可）、
それ以外のユーザーを参照（読み取り専用）として開く。
"""
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QInputDialog,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

import database as db
from sync import presence

_INVALID_CHARS = set(r'\/:*?"<>|')


class UserSelectDialog(QDialog):

    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self._folder   = folder
        self._selected = ""
        self.setWindowTitle("ユーザーを選択")
        self.setMinimumSize(560, 400)
        self._build_ui()
        self._reload()

    # ── 公開 ──────────────────────────────────────────────────────────────────

    def selected_user(self) -> str:
        return self._selected

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        info = QLabel(
            "<b>自分のユーザーをクリックしてください。</b><br>"
            "選んだユーザーのデータが <b>メイン（編集可）</b> になり、"
            "他のユーザーのデータは <b>参照（読み取り専用）</b> で表示されます。"
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        layout.addWidget(info)

        folder_lbl = QLabel(f"共有フォルダ: {self._folder}")
        folder_lbl.setStyleSheet("color:#666; font-size:10px;")
        folder_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(folder_lbl)

        self._list = QListWidget()
        self._list.setSpacing(2)
        self._list.setStyleSheet(
            "QListWidget::item { padding: 6px; border-bottom: 1px solid #E0E0E0; }"
            "QListWidget::item:selected { background: #BBDEFB; color: #000; }"
        )
        self._list.itemDoubleClicked.connect(lambda _: self._accept_selected())
        self._list.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self._list, 1)

        btns = QHBoxLayout()
        add_btn = QPushButton("＋ 新しいユーザーを追加")
        add_btn.clicked.connect(self._add_user)
        btns.addWidget(add_btn)

        reload_btn = QPushButton("⟳ 再読込")
        reload_btn.setToolTip("BOX Drive の同期後に一覧を更新します")
        reload_btn.clicked.connect(self._reload)
        btns.addWidget(reload_btn)
        btns.addStretch()

        self._ok_btn = QPushButton("このユーザーで開く")
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._accept_selected)
        btns.addWidget(self._ok_btn)

        cancel_btn = QPushButton("終了")
        cancel_btn.setStyleSheet(
            "QPushButton { background-color: #757575; }"
            "QPushButton:hover { background-color: #616161; }"
        )
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    # ── 一覧 ──────────────────────────────────────────────────────────────────

    def _reload(self):
        current = self._list.currentItem().data(Qt.UserRole) if self._list.currentItem() else ""
        prefer  = current or db.get_user_name()

        self._list.clear()
        for u in presence.list_users(self._folder):
            self._list.addItem(self._make_item(u))

        target = 0
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.UserRole) == prefer:
                target = i
                break
        if self._list.count():
            self._list.setCurrentRow(target)
        self._ok_btn.setEnabled(self._list.count() > 0)

    def _make_item(self, u: dict) -> QListWidgetItem:
        lock    = u["lock"]
        workers = "、".join(u["workers"]) or "（担当者未登録）"
        mtime   = u["mtime"].strftime("%m/%d %H:%M") if u["mtime"] else "-"
        if not u["readable"]:
            detail = "※ 読み込めません（BOX 同期中・破損の可能性）"
        else:
            detail = f"担当者: {workers}　予定 {u['schedules']} 件　最終更新 {mtime}"

        if lock and not presence.is_mine(lock):
            status = f"🟢 使用中（{lock.get('host', '?')} で {lock.get('started', '')[11:16]} から）"
        else:
            status = "⚪ 未使用"

        it = QListWidgetItem(f"{u['name']}　　{status}\n    {detail}")
        it.setData(Qt.UserRole, u["name"])
        it.setData(Qt.UserRole + 1, lock)
        f = it.font(); f.setPointSize(10); it.setFont(f)
        if lock and not presence.is_mine(lock):
            it.setForeground(QColor("#2E7D32"))
        return it

    def _on_current_changed(self, cur, _prev):
        self._ok_btn.setEnabled(cur is not None)

    # ── 操作 ──────────────────────────────────────────────────────────────────

    def _accept_selected(self):
        it = self._list.currentItem()
        if it is None:
            return
        name = it.data(Qt.UserRole)
        lock = presence.read_lock(self._folder, name)   # 選択時点の最新状態で判定
        if lock and not presence.is_mine(lock):
            ret = QMessageBox.warning(
                self, "使用中のユーザー",
                f"「{name}」は現在 {lock.get('host', '?')} で開かれています。\n\n"
                "同じユーザーを2台で同時に編集すると、BOX Drive の同期で\n"
                "どちらかの変更が失われる恐れがあります。\n\n"
                f"それでも「{name}」をメインで開きますか？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return
        self._selected = name
        self.accept()

    def _add_user(self):
        name, ok = QInputDialog.getText(
            self, "新しいユーザーを追加",
            "ユーザー名（DBファイル名になります。例: 山田）:",
        )
        name = name.strip()
        if not ok or not name:
            return
        if any(c in _INVALID_CHARS for c in name):
            QMessageBox.warning(self, "ユーザー名エラー",
                                r'ユーザー名に次の文字は使用できません: \ / : * ? " < > |')
            return
        if (self._folder / f"{name}.db").exists():
            QMessageBox.information(self, "既に存在します",
                                    f"「{name}」は既に一覧にあります。")
            self._reload()
            return
        # DB の作成は init_db() に任せる（選択後の通常起動処理で作成される）
        self._selected = name
        self.accept()
