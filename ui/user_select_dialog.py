"""起動時のユーザー選択ダイアログ（「ユーザー選択」「初期設定」の2タブ）。

ユーザー選択: 共有フォルダ内のユーザーDB一覧から自分を選ぶ。選んだユーザーを
              メイン（編集可）、それ以外のユーザーを参照（読み取り専用）として開く。
初期設定    : 共有フォルダの場所・自分のユーザー名・Excelバックアップ先を設定する。
              共有しない個人用（DBファイル直接指定）もここから選べる。
"""
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QMessageBox, QInputDialog, QTabWidget, QWidget, QGroupBox,
    QFormLayout, QLineEdit, QFileDialog,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

import database as db
from sync import auth, presence
from ui.password_dialogs import ask_password, PasswordChangeDialog

_INVALID_CHARS = set(r'\/:*?"<>|')
_INVALID_MSG   = r'ユーザー名に次の文字は使用できません: \ / : * ? " < > |'

TAB_SELECT = 0
TAB_SETUP  = 1

_ADMIN_KEY = "\x00admin"   # 一覧の管理者項目の識別子（ユーザー名と衝突しない）


class UserSelectDialog(QDialog):

    def __init__(self, folder: Path | None, parent=None):
        super().__init__(parent)
        self._folder       = folder
        self._selected     = ""
        self._backup_dir   = ""
        self._admin        = False
        self._new_password = ""
        self.setWindowTitle("ユーザーを選択")
        self.setMinimumSize(600, 460)
        self._build_ui()
        self._reload()
        # 共有フォルダが未設定・見つからない（初回起動など）は初期設定タブから始める
        if not self._folder_ok():
            self._tabs.setCurrentIndex(TAB_SETUP)

    # ── 公開 ──────────────────────────────────────────────────────────────────

    def selected_user(self) -> str:
        """メインで開くユーザー名。個人用（直接指定）を選んだ場合は空文字。"""
        return self._selected

    def is_admin(self) -> bool:
        """管理者としてログインしたか（selected_user は最初の編集対象）。"""
        return self._admin

    def new_user_password(self) -> str:
        """新規ユーザー追加時に設定されたパスワード（DB作成後に呼び出し側が保存する）。"""
        return self._new_password

    def backup_dir(self) -> str:
        """初期設定タブで入力された Excel バックアップ先（未入力なら空文字）。
        保存先はユーザーごとのDBに記録されるため、DBを開いた後で呼び出し側が反映する。"""
        return self._backup_dir

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_select_tab(), "ユーザー選択")
        self._tabs.addTab(self._build_setup_tab(), "初期設定（フォルダの場所など）")
        layout.addWidget(self._tabs, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        cancel_btn = QPushButton("終了")
        cancel_btn.setStyleSheet(
            "QPushButton { background-color: #757575; }"
            "QPushButton:hover { background-color: #616161; }"
        )
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)
        layout.addLayout(bottom)

    def _build_select_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        info = QLabel(
            "<b>自分のユーザーをクリックしてください。</b><br>"
            "選んだユーザーのデータが <b>メイン（編集可）</b> になり、"
            "他のユーザーのデータは <b>参照（読み取り専用）</b> で表示されます。<br>"
            "🔑 管理者 は全ユーザーのデータを切り替えて編集できます。"
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        layout.addWidget(info)

        self._folder_lbl = QLabel()
        self._folder_lbl.setStyleSheet("color:#666; font-size:10px;")
        self._folder_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._folder_lbl)

        self._list = QListWidget()
        self._list.setSpacing(2)
        self._list.setStyleSheet(
            "QListWidget::item { padding: 6px; border-bottom: 1px solid #E0E0E0; }"
            "QListWidget::item:selected { background: #BBDEFB; color: #000; }"
        )
        self._list.itemDoubleClicked.connect(lambda _: self._accept_selected())
        self._list.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self._list, 1)

        self._empty_lbl = QLabel()
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setStyleSheet("color:#C62828;")
        layout.addWidget(self._empty_lbl)

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
        layout.addLayout(btns)
        return w

    def _build_setup_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(10)

        info = QLabel(
            "初めて使うときや、共有フォルダの場所を変えるときはここで設定します。<br>"
            "チームで共有する場合は、全員が <b>同じ BOX Drive のフォルダ</b> を指定してください。"
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        layout.addWidget(info)

        # ① 共有フォルダ
        g1 = QGroupBox("① 共有フォルダ（BOX Drive）")
        f1 = QFormLayout(g1)
        row = QHBoxLayout()
        self._folder_edit = QLineEdit(str(self._folder) if self._folder else "")
        self._folder_edit.setPlaceholderText("例: C:\\Users\\yourname\\Box\\チーム共有\\作業予定")
        row.addWidget(self._folder_edit)
        browse = QPushButton("参照...")
        browse.setFixedWidth(72)
        browse.clicked.connect(self._browse_folder)
        row.addWidget(browse)
        f1.addRow("フォルダ:", row)
        self._folder_status = QLabel()
        self._folder_status.setStyleSheet("font-size:10px;")
        f1.addRow("", self._folder_status)
        layout.addWidget(g1)

        # ② 自分のユーザー名
        g2 = QGroupBox("② 自分のユーザー名")
        f2 = QFormLayout(g2)
        self._user_edit = QLineEdit(db.get_user_name())
        self._user_edit.setPlaceholderText("例: 山田（自分のDBファイル名 山田.db になります）")
        f2.addRow("ユーザー名:", self._user_edit)
        self._user_preview = QLabel()
        self._user_preview.setStyleSheet("color:#1565C0; font-size:10px;")
        f2.addRow("自分のDB:", self._user_preview)
        layout.addWidget(g2)

        # ③ Excel バックアップ先
        g3 = QGroupBox("③ Excel バックアップの保存先（任意）")
        f3 = QFormLayout(g3)
        row3 = QHBoxLayout()
        self._backup_edit = QLineEdit()
        self._backup_edit.setPlaceholderText("空欄 = 共有フォルダ内の backup_excel（既定）")
        row3.addWidget(self._backup_edit)
        browse3 = QPushButton("参照...")
        browse3.setFixedWidth(72)
        browse3.clicked.connect(self._browse_backup)
        row3.addWidget(browse3)
        f3.addRow("フォルダ:", row3)
        layout.addWidget(g3)

        layout.addStretch()

        btns = QHBoxLayout()
        personal_btn = QPushButton("個人用（共有しない）で使う...")
        personal_btn.setToolTip("共有せず、DBファイルを直接指定して1人で使います")
        personal_btn.setStyleSheet(
            "QPushButton { background-color: #607D8B; }"
            "QPushButton:hover { background-color: #546E7A; }"
        )
        personal_btn.clicked.connect(self._use_personal)
        btns.addWidget(personal_btn)
        btns.addStretch()

        save_btn = QPushButton("フォルダを保存して一覧へ")
        save_btn.setToolTip("共有フォルダだけ保存し、「ユーザー選択」タブで自分を選びます")
        save_btn.clicked.connect(self._save_folder_only)
        btns.addWidget(save_btn)

        open_btn = QPushButton("保存してこのユーザーで開く")
        open_btn.clicked.connect(self._save_and_open)
        btns.addWidget(open_btn)
        layout.addLayout(btns)

        self._folder_edit.textChanged.connect(self._update_setup_status)
        self._user_edit.textChanged.connect(self._update_setup_status)
        self._update_setup_status()
        return w

    # ── ユーザー選択タブ ──────────────────────────────────────────────────────

    def _folder_ok(self) -> bool:
        return self._folder is not None and self._folder.exists()

    def _reload(self):
        current = self._list.currentItem().data(Qt.UserRole) if self._list.currentItem() else ""
        prefer  = current or db.get_user_name()

        self._list.clear()
        if self._folder is None:
            self._folder_lbl.setText("共有フォルダ: （未設定）")
            self._empty_lbl.setText("共有フォルダが未設定です。「初期設定」タブで場所を設定してください。")
        elif not self._folder.exists():
            self._folder_lbl.setText(f"共有フォルダ: {self._folder}")
            self._empty_lbl.setText(
                "共有フォルダが見つかりません。BOX Drive が起動・同期済みか確認するか、"
                "「初期設定」タブで場所を設定し直してください。"
            )
        else:
            self._folder_lbl.setText(f"共有フォルダ: {self._folder}")
            try:
                auth.ensure_admin(self._folder)   # 管理者は既定で作成（初期パスワード admin）
            except OSError:
                pass
            self._list.addItem(self._make_admin_item())
            users = presence.list_users(self._folder)
            for u in users:
                self._list.addItem(self._make_item(u))
            self._empty_lbl.setText(
                "" if users else
                "まだユーザーがいません。「＋ 新しいユーザーを追加」で自分を追加してください。"
            )
        self._empty_lbl.setVisible(bool(self._empty_lbl.text()))

        target = 1 if self._list.count() > 1 else 0   # 既定は管理者の次（最初のユーザー）
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.UserRole) == prefer:
                target = i
                break
        if self._list.count():
            self._list.setCurrentRow(target)
        self._ok_btn.setEnabled(self._list.count() > 0)

    def _make_admin_item(self) -> QListWidgetItem:
        detail = "全ユーザーのデータを編集できます（編集対象を切り替え）"
        if auth.admin_must_change(self._folder):
            detail += f"\n    初期パスワード: {auth.DEFAULT_ADMIN_PW}（初回ログイン時に変更します）"
        it = QListWidgetItem(f"🔑 {auth.ADMIN_LABEL}\n    {detail}")
        it.setData(Qt.UserRole, _ADMIN_KEY)
        f = it.font(); f.setPointSize(10); f.setBold(True); it.setFont(f)
        it.setForeground(QColor("#6A1B9A"))
        return it

    def _make_item(self, u: dict) -> QListWidgetItem:
        lock    = u["lock"]
        workers = "、".join(u["workers"]) or "（担当者未登録）"
        mtime   = u["mtime"].strftime("%m/%d %H:%M") if u["mtime"] else "-"
        if not u["readable"]:
            detail = "※ 読み込めません（BOX 同期中・破損の可能性）"
        else:
            detail = f"担当者: {workers}　予定 {u['schedules']} 件　最終更新 {mtime}"

        if lock and not presence.is_mine(lock):
            who = "管理者が編集中" if lock.get("admin") else "使用中"
            status = f"🟢 {who}（{lock.get('host', '?')} で {lock.get('started', '')[11:16]} から）"
        else:
            status = "⚪ 未使用"
        key = "🔒 " if u.get("has_password") else ""

        it = QListWidgetItem(f"{key}{u['name']}　　{status}\n    {detail}")
        it.setData(Qt.UserRole, u["name"])
        it.setData(Qt.UserRole + 1, lock)
        f = it.font(); f.setPointSize(10); it.setFont(f)
        if lock and not presence.is_mine(lock):
            it.setForeground(QColor("#2E7D32"))
        return it

    def _on_current_changed(self, cur, _prev):
        self._ok_btn.setEnabled(cur is not None)

    def _accept_selected(self):
        it = self._list.currentItem()
        if it is None:
            return
        name = it.data(Qt.UserRole)
        if name == _ADMIN_KEY:
            self._login_admin()
            return
        if not self._check_user_password(name):
            return
        if not self._confirm_if_in_use(name):
            return
        self._selected = name
        self.accept()

    def _check_user_password(self, name: str) -> bool:
        """パスワードが設定されたユーザーなら入力させて照合する。"""
        path = auth.user_db_path(self._folder, name)
        if not auth.user_has_password(path):
            return True
        pw = ask_password(self, "パスワード", f"「{name}」のパスワードを入力してください。")
        if pw is None:
            return False
        if not auth.verify_user(path, pw):
            QMessageBox.warning(self, "パスワードエラー", "パスワードが違います。")
            return False
        return True

    def _login_admin(self):
        users = [u["name"] for u in presence.list_users(self._folder)]
        if not users:
            QMessageBox.information(
                self, "ユーザーがいません",
                "管理者で編集するユーザーがまだいません。\n先に「＋ 新しいユーザーを追加」でユーザーを作成してください。",
            )
            return
        pw = ask_password(self, "管理者ログイン", f"{auth.ADMIN_LABEL}のパスワードを入力してください。")
        if pw is None:
            return
        if not auth.verify_admin(self._folder, pw):
            QMessageBox.warning(self, "パスワードエラー", "管理者のパスワードが違います。")
            return
        if auth.admin_must_change(self._folder):
            dlg = PasswordChangeDialog(
                self, title="管理者パスワードの変更（必須）",
                message="初期パスワードのままです。<b>新しい管理者パスワード</b>を設定してください。",
                allow_empty=False, forbidden={auth.DEFAULT_ADMIN_PW},
            )
            if dlg.exec_() != QDialog.Accepted:
                return
            auth.set_admin_password(self._folder, dlg.password())

        last   = db.get_user_name()
        target = last if last in users else users[0]
        if not self._confirm_if_in_use(target):
            return
        self._admin    = True
        self._selected = target
        self.accept()

    def _confirm_if_in_use(self, name: str) -> bool:
        """他PCで使用中なら警告し、続行してよいかを返す（選択時点の最新状態で判定）。"""
        lock = presence.read_lock(self._folder, name)
        if not lock or presence.is_mine(lock):
            return True
        ret = QMessageBox.warning(
            self, "使用中のユーザー",
            f"「{name}」は現在 {lock.get('host', '?')} で開かれています。\n\n"
            "同じユーザーを2台で同時に編集すると、BOX Drive の同期で\n"
            "どちらかの変更が失われる恐れがあります。\n\n"
            f"それでも「{name}」をメインで開きますか？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        return ret == QMessageBox.Yes

    def _add_user(self):
        if not self._folder_ok():
            self._tabs.setCurrentIndex(TAB_SETUP)
            return
        name, ok = QInputDialog.getText(
            self, "新しいユーザーを追加",
            "ユーザー名（DBファイル名になります。例: 山田）:",
        )
        name = name.strip()
        if not ok or not name:
            return
        if not self._valid_user_name(name):
            return
        if (self._folder / f"{name}.db").exists():
            QMessageBox.information(self, "既に存在します",
                                    f"「{name}」は既に一覧にあります。")
            self._reload()
            return
        pw_dlg = PasswordChangeDialog(
            self, title="パスワードの設定（任意）",
            message=f"「{name}」のパスワードを設定できます。<br>空欄のままOKでパスワードなしになります。",
        )
        if pw_dlg.exec_() != QDialog.Accepted:
            return
        # DB の作成は init_db() に任せ、パスワードは作成後に呼び出し側が保存する
        self._new_password = pw_dlg.password()
        self._selected = name
        self.accept()

    def _valid_user_name(self, name: str) -> bool:
        if any(c in _INVALID_CHARS for c in name):
            QMessageBox.warning(self, "ユーザー名エラー", _INVALID_MSG)
            return False
        if name == auth.ADMIN_LABEL:
            QMessageBox.warning(self, "ユーザー名エラー",
                                f"「{auth.ADMIN_LABEL}」はユーザー名に使用できません。")
            return False
        return True

    # ── 初期設定タブ ──────────────────────────────────────────────────────────

    def _browse_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, "共有フォルダを選択（「新しいフォルダー」で作成もできます）",
            self._folder_edit.text() or str(Path.home()),
            QFileDialog.ShowDirsOnly,
        )
        if d:
            self._folder_edit.setText(str(Path(d)))

    def _browse_backup(self):
        d = QFileDialog.getExistingDirectory(
            self, "Excel バックアップの保存先を選択",
            self._backup_edit.text() or self._folder_edit.text() or str(Path.home()),
            QFileDialog.ShowDirsOnly,
        )
        if d:
            self._backup_edit.setText(str(Path(d)))

    def _update_setup_status(self):
        text = self._folder_edit.text().strip()
        user = self._user_edit.text().strip()
        if not text:
            self._folder_status.setText("フォルダを指定してください")
            self._folder_status.setStyleSheet("color:#C62828; font-size:10px;")
        else:
            p = Path(text)
            if p.is_dir():
                n = len(list(p.glob("*.db")))
                self._folder_status.setText(f"✔ フォルダあり（ユーザーDB {n} 件）")
                self._folder_status.setStyleSheet("color:#2E7D32; font-size:10px;")
            else:
                self._folder_status.setText("フォルダがありません（保存時に作成します）")
                self._folder_status.setStyleSheet("color:#E65100; font-size:10px;")

        if text and user:
            p = Path(text) / f"{user}.db"
            self._user_preview.setText(f"{p}　{'（既存）' if p.exists() else '（新規作成）'}")
        else:
            self._user_preview.setText("（フォルダとユーザー名を入力すると表示されます）")

    def _apply_folder(self) -> bool:
        """入力された共有フォルダを検証・作成し、設定に保存する。"""
        text = self._folder_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "入力エラー", "共有フォルダを指定してください。")
            return False
        folder = Path(text)
        if not folder.is_dir():
            ret = QMessageBox.question(
                self, "フォルダの作成",
                f"フォルダが見つかりません:\n{folder}\n\n新しく作成しますか？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                return False
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, "作成エラー", f"フォルダを作成できませんでした。\n\n{e}")
                return False
        db.set_shared_folder(folder)
        self._folder = folder
        self._backup_dir = self._backup_edit.text().strip()
        return True

    def _save_folder_only(self):
        if not self._apply_folder():
            return
        self._reload()
        self._tabs.setCurrentIndex(TAB_SELECT)

    def _save_and_open(self):
        user = self._user_edit.text().strip()
        if not user:
            QMessageBox.warning(self, "入力エラー", "自分のユーザー名を入力してください。")
            return
        if not self._valid_user_name(user):
            return
        if not self._apply_folder():
            return
        if not self._check_user_password(user):
            return
        if not self._confirm_if_in_use(user):
            return
        self._selected = user
        self.accept()

    def _use_personal(self):
        cur = db.get_db_path()
        path, _ = QFileDialog.getSaveFileName(
            self, "個人用DBファイルの場所を選択（新規作成も可）",
            str(cur) if cur else str(db._DEFAULT_DB_PATH),
            "SQLite Database (*.db);;All Files (*)",
        )
        if not path:
            return
        p = Path(path)
        if not p.parent.exists():
            QMessageBox.warning(self, "フォルダが存在しません",
                                f"フォルダが見つかりません:\n{p.parent}")
            return
        db.set_db_path(p)
        db.clear_shared_folder()
        self._selected   = ""
        self._backup_dir = self._backup_edit.text().strip()
        self.accept()
