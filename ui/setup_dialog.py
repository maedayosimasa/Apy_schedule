"""BOX 共有フォルダの設定ダイアログ。"""
from pathlib import Path
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QDialogButtonBox, QMessageBox,
)
from PyQt5.QtCore import Qt
import database as db


class DbPathDialog(QDialog):
    """DB ファイルのパスを設定するダイアログ。"""

    def __init__(self, parent=None, first_run: bool = False):
        super().__init__(parent)
        self._first_run = first_run
        self.setWindowTitle("データベースの場所を設定")
        self.setMinimumWidth(520)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        if self._first_run:
            msg = (
                "<b>初回起動：共有データベースの場所を設定してください。</b><br><br>"
                "BOX Drive でチーム共有フォルダを同期済みの場合は、<br>"
                "そのフォルダ内にある（または作成する）<code>schedule.db</code> を指定します。<br><br>"
                "例）<code>C:\\Users\\yourname\\Box\\チーム共有\\schedule.db</code>"
            )
        else:
            msg = (
                "データベースファイルのパスを変更します。<br>"
                "BOX Drive の共有フォルダを指定することで複数人で共有できます。"
            )
        label = QLabel(msg)
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        layout.addWidget(label)

        # パス入力行
        row = QHBoxLayout()
        self._path_edit = QLineEdit()
        current = db.get_db_path()
        if current:
            self._path_edit.setText(str(current))
        else:
            self._path_edit.setPlaceholderText("例: C:\\Users\\yourname\\Box\\共有フォルダ\\schedule.db")
        row.addWidget(self._path_edit)

        browse_btn = QPushButton("参照...")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        # 現在の設定表示
        info_label = QLabel(f"現在のパス: {db.DB_PATH}")
        info_label.setStyleSheet("color: #555; font-size: 9px;")
        layout.addWidget(info_label)

        # ボタン
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        if self._first_run:
            buttons.button(QDialogButtonBox.Cancel).setText("EXEと同じフォルダを使う")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "DB ファイルの場所を選択（新規作成も可）",
            str(db.DB_PATH),
            "SQLite Database (*.db);;All Files (*)",
        )
        if path:
            self._path_edit.setText(path)

    def _accept(self):
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
                f"フォルダが見つかりません:\n{p.parent}\n\nBOX Drive が同期済みか確認してください。"
            )
            return

        db.set_db_path(p)
        db.refresh_db_path()
        self.accept()
