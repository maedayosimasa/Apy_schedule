"""パスワード入力・変更ダイアログ。"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel, QLineEdit, QDialogButtonBox,
    QMessageBox,
)
from PyQt5.QtCore import Qt


def ask_password(parent, title: str, message: str) -> str | None:
    """パスワードを1回入力させる。キャンセル時は None。"""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(340)
    layout = QVBoxLayout(dlg)
    lbl = QLabel(message)
    lbl.setWordWrap(True)
    layout.addWidget(lbl)
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.Password)
    layout.addWidget(edit)
    btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)
    layout.addWidget(btns)
    edit.setFocus()
    if dlg.exec_() != QDialog.Accepted:
        return None
    return edit.text()


class PasswordChangeDialog(QDialog):
    """新しいパスワードを2回入力させるダイアログ。

    verify_current: 現在のパスワードを確認する関数（None なら確認しない）
    allow_empty   : 空欄で「パスワードなし」にできるか（管理者は不可）
    forbidden     : 使用を禁止するパスワード（初期パスワードなど）
    """

    def __init__(self, parent=None, *, title="パスワードの変更", message="",
                 verify_current=None, allow_empty=True, forbidden=()):
        super().__init__(parent)
        self._verify_current = verify_current
        self._allow_empty    = allow_empty
        self._forbidden      = set(forbidden)
        self._password       = ""
        self.setWindowTitle(title)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        if message:
            lbl = QLabel(message)
            lbl.setWordWrap(True)
            lbl.setTextFormat(Qt.RichText)
            layout.addWidget(lbl)

        form = QFormLayout()
        self._current = QLineEdit()
        self._current.setEchoMode(QLineEdit.Password)
        if verify_current is not None:
            form.addRow("現在のパスワード:", self._current)
        self._new = QLineEdit()
        self._new.setEchoMode(QLineEdit.Password)
        if allow_empty:
            self._new.setPlaceholderText("空欄にするとパスワードなし")
        form.addRow("新しいパスワード:", self._new)
        self._confirm = QLineEdit()
        self._confirm.setEchoMode(QLineEdit.Password)
        form.addRow("新しいパスワード（確認）:", self._confirm)
        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def password(self) -> str:
        """確定した新しいパスワード（空文字 = パスワードなし）。"""
        return self._password

    def _accept(self):
        if self._verify_current is not None and not self._verify_current(self._current.text()):
            QMessageBox.warning(self, "パスワードエラー", "現在のパスワードが違います。")
            return
        new = self._new.text()
        if new != self._confirm.text():
            QMessageBox.warning(self, "入力エラー", "新しいパスワードが一致しません。")
            return
        if not new and not self._allow_empty:
            QMessageBox.warning(self, "入力エラー", "パスワードを入力してください。")
            return
        if new in self._forbidden:
            QMessageBox.warning(self, "入力エラー", "このパスワードは使用できません。別のパスワードにしてください。")
            return
        self._password = new
        self.accept()
