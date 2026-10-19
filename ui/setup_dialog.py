"""DB接続設定ダイアログ（共有フォルダ＋ユーザー名 / 直接パス指定の2モード）。"""
from pathlib import Path
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QDialogButtonBox, QMessageBox,
    QGroupBox, QRadioButton, QButtonGroup, QFormLayout,
)
from PyQt5.QtCore import Qt
import database as db


class DbPathDialog(QDialog):

    def __init__(self, parent=None, first_run: bool = False):
        super().__init__(parent)
        self._first_run = first_run
        self.setWindowTitle("データベースの場所を設定")
        self.setMinimumWidth(540)
        self._build_ui()
        self._load_current_config()

    # ── UI構築 ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        if self._first_run:
            info = QLabel(
                "<b>初回起動：データベースの場所を設定してください。</b><br>"
                "複数人でBOX共有する場合は「共有フォルダで使う」を選択してください。"
            )
        else:
            info = QLabel("データベースの接続設定を変更します。")
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        layout.addWidget(info)

        # ── モード選択 ────────────────────────────────────────────────────────
        self._radio_shared = QRadioButton("共有フォルダで使う（BOX Drive・複数人共有）")
        self._radio_direct = QRadioButton("直接DBファイルを指定する（個人・単独使用）")
        self._mode_group   = QButtonGroup(self)
        self._mode_group.addButton(self._radio_shared, 0)
        self._mode_group.addButton(self._radio_direct, 1)
        self._radio_shared.setChecked(True)

        mode_box = QGroupBox("使用モード")
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.addWidget(self._radio_shared)
        mode_layout.addWidget(self._radio_direct)
        layout.addWidget(mode_box)

        # ── 共有モード設定 ────────────────────────────────────────────────────
        self._shared_group = QGroupBox("共有フォルダ設定")
        shared_form = QFormLayout(self._shared_group)
        shared_form.setRowWrapPolicy(QFormLayout.WrapLongRows)

        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("例: C:\\Users\\yourname\\Box\\チーム共有")
        folder_row.addWidget(self._folder_edit)
        folder_browse = QPushButton("参照...")
        folder_browse.setFixedWidth(72)
        folder_browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(folder_browse)
        shared_form.addRow("共有フォルダ:", folder_row)

        self._username_edit = QLineEdit()
        self._username_edit.setPlaceholderText("例: yamada  (自分のDB名: yamada.db)")
        shared_form.addRow("ユーザー名:", self._username_edit)

        self._preview_label = QLabel("")
        self._preview_label.setStyleSheet("color: #1565C0; font-size: 10px;")
        shared_form.addRow("自DBパス:", self._preview_label)

        layout.addWidget(self._shared_group)

        # ── 直接指定モード設定 ────────────────────────────────────────────────
        self._direct_group = QGroupBox("DBファイルパス")
        direct_form = QFormLayout(self._direct_group)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("例: C:\\Users\\yourname\\Box\\共有\\schedule.db")
        path_row.addWidget(self._path_edit)
        path_browse = QPushButton("参照...")
        path_browse.setFixedWidth(72)
        path_browse.clicked.connect(self._browse_file)
        path_row.addWidget(path_browse)
        direct_form.addRow("DBファイル:", path_row)

        layout.addWidget(self._direct_group)

        # ── ボタン ────────────────────────────────────────────────────────────
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        if self._first_run:
            buttons.button(QDialogButtonBox.Cancel).setText("EXEと同じフォルダを使う")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # イベント接続
        self._radio_shared.toggled.connect(self._on_mode_changed)
        self._folder_edit.textChanged.connect(self._update_preview)
        self._username_edit.textChanged.connect(self._update_preview)
        self._on_mode_changed()

    # ── 現在設定のロード ──────────────────────────────────────────────────────

    def _load_current_config(self):
        shared_folder = db.get_shared_folder()
        user_name     = db.get_user_name()
        db_path       = db.get_db_path()

        if shared_folder or user_name:
            self._radio_shared.setChecked(True)
            if shared_folder:
                self._folder_edit.setText(str(shared_folder))
            if user_name:
                self._username_edit.setText(user_name)
        elif db_path:
            self._radio_direct.setChecked(True)
            self._path_edit.setText(str(db_path))
        else:
            self._radio_shared.setChecked(True)

        self._on_mode_changed()

    # ── スロット ──────────────────────────────────────────────────────────────

    def _on_mode_changed(self):
        shared = self._radio_shared.isChecked()
        self._shared_group.setEnabled(shared)
        self._direct_group.setEnabled(not shared)

    def _update_preview(self):
        folder = self._folder_edit.text().strip()
        user   = self._username_edit.text().strip()
        if folder and user:
            self._preview_label.setText(str(Path(folder) / f"{user}.db"))
        else:
            self._preview_label.setText("（フォルダとユーザー名を入力すると表示されます）")

    def _browse_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, "共有フォルダを選択",
            self._folder_edit.text() or str(Path.home()),
            QFileDialog.ShowDirsOnly,
        )
        if d:
            self._folder_edit.setText(d)

    def _browse_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "DBファイルの場所を選択（新規作成も可）",
            self._path_edit.text() or str(db.DB_PATH),
            "SQLite Database (*.db);;All Files (*)",
        )
        if path:
            self._path_edit.setText(path)

    # ── OK処理 ────────────────────────────────────────────────────────────────

    def _accept(self):
        if self._radio_shared.isChecked():
            self._accept_shared_mode()
        else:
            self._accept_direct_mode()

    def _accept_shared_mode(self):
        folder = self._folder_edit.text().strip()
        user   = self._username_edit.text().strip()

        if not folder:
            QMessageBox.warning(self, "入力エラー", "共有フォルダを指定してください。")
            return
        if not user:
            QMessageBox.warning(self, "入力エラー", "ユーザー名を入力してください。")
            return

        folder_path = Path(folder)
        if not folder_path.exists():
            QMessageBox.warning(
                self, "フォルダが存在しません",
                f"フォルダが見つかりません:\n{folder_path}\n\nBOX Driveが同期済みか確認してください。"
            )
            return

        # ユーザー名に使えない文字チェック（ファイル名になるため）
        invalid = set(r'\/:*?"<>|')
        if any(c in invalid for c in user):
            QMessageBox.warning(self, "ユーザー名エラー",
                                r'ユーザー名に次の文字は使用できません: \ / : * ? " < > |')
            return

        db.set_shared_folder(folder_path)
        db.set_user_name(user)
        db.refresh_db_path()
        self.accept()

    def _accept_direct_mode(self):
        text = self._path_edit.text().strip()
        if not text:
            if self._first_run:
                self.reject()
                return
            QMessageBox.warning(self, "入力エラー", "パスを入力してください。")
            return

        p = Path(text)
        if not p.parent.exists():
            QMessageBox.warning(
                self, "フォルダが存在しません",
                f"フォルダが見つかりません:\n{p.parent}\n\nBOX Driveが同期済みか確認してください。"
            )
            return

        db.set_db_path(p)
        db.refresh_db_path()
        self.accept()
