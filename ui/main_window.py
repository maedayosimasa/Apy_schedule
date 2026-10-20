from datetime import date as _date, timedelta
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QTabWidget, QToolBar, QAction,
    QMessageBox, QApplication, QDialog, QFormLayout, QLineEdit,
    QPushButton, QHBoxLayout, QCheckBox, QFileDialog, QDialogButtonBox,
    QLabel, QComboBox, QInputDialog,
)
from PyQt5.QtGui import QKeySequence
from PyQt5.QtCore import Qt, QTimer, QSettings, QRect
from ui.schedule_tab  import ScheduleTab
from ui.actual_tab    import ActualTab
from ui.gantt_tab     import GanttTab
from ui.monthly_tab   import MonthlyTab
from ui.chart_widget  import ChartWidget
from ui.master_tab    import MasterTab
from ui.history_tab   import HistoryTab
from ui.shared_tab    import SharedTab
import database as db
import excel_backup
from version import APP_NAME, APP_VERSION

_AUTO_REFRESH_INTERVAL_MS = 60 * 1000  # 60秒ごとに自動リフレッシュ
_SETTINGS_ORG = "AipySchedule"
_SETTINGS_APP = "MainWindow"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(1100, 720)
        self._today   = _date.today()
        self._watcher = None
        self._presence_user = None   # メインで開いているユーザー（ロック保持中）
        self._update_window_title()
        self._start_presence()
        self._setup_ui()
        self._restore_state()
        self._start_auto_refresh()
        self._init_shared_sync()
        QTimer.singleShot(2000, self._startup_backup_check)

    def _setup_ui(self):
        # ── ツールバー ──────────────────────────────────────────────────────────
        toolbar = QToolBar("編集")
        toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        self._undo_action = QAction("↩ 戻る", self)
        self._undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self._undo_action.setToolTip("直前の操作を元に戻す (Ctrl+Z)")
        self._undo_action.setEnabled(False)
        self._undo_action.triggered.connect(self._undo)
        toolbar.addAction(self._undo_action)

        self._redo_action = QAction("↪ 進む", self)
        self._redo_action.setShortcut(QKeySequence("Ctrl+Y"))
        self._redo_action.setToolTip("元に戻した操作をやり直す (Ctrl+Y)")
        self._redo_action.setEnabled(False)
        self._redo_action.triggered.connect(self._redo)
        toolbar.addAction(self._redo_action)

        toolbar.addSeparator()

        refresh_action = QAction("⟳ 今すぐ更新", self)
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.setToolTip("他のユーザーの変更を取得する (F5)")
        refresh_action.triggered.connect(self._manual_refresh)
        toolbar.addAction(refresh_action)

        toolbar.addSeparator()

        settings_action = QAction("⚙ 設定", self)
        settings_action.setToolTip("データベースの場所を変更する")
        settings_action.triggered.connect(self._open_settings)
        toolbar.addAction(settings_action)

        self._password_action = QAction("🔒 パスワード", self)
        self._password_action.setToolTip("ログインパスワードの設定・変更")
        self._password_action.triggered.connect(self._change_password)
        toolbar.addAction(self._password_action)

        # 管理者用：編集対象ユーザーの切り替え
        self._admin_sep = toolbar.addSeparator()
        self._admin_label = QLabel("  🔑 管理者　編集対象: ")
        self._admin_label.setStyleSheet("color:#6A1B9A; font-weight:bold;")
        self._admin_label_action = toolbar.addWidget(self._admin_label)
        self._target_combo = QComboBox()
        self._target_combo.setMinimumWidth(120)
        self._target_combo.setToolTip("管理者：編集するユーザーを切り替えます")
        self._target_combo.activated[str].connect(self._on_target_selected)
        self._target_combo_action = toolbar.addWidget(self._target_combo)

        toolbar.addSeparator()

        excel_action = QAction("📊 Excel出力", self)
        excel_action.setToolTip("今日のデータを Excel に手動保存する")
        excel_action.triggered.connect(self._excel_backup_today)
        toolbar.addAction(excel_action)

        excel_cfg_action = QAction("📁 Excel設定", self)
        excel_cfg_action.setToolTip("Excel バックアップの設定（保存先・自動保存のオン/オフ）")
        excel_cfg_action.triggered.connect(self._open_excel_settings)
        toolbar.addAction(excel_cfg_action)

        toolbar.addSeparator()

        about_action = QAction(f"ℹ v{APP_VERSION}", self)
        about_action.setToolTip("バージョン情報・変更履歴")
        about_action.triggered.connect(self._open_about)
        toolbar.addAction(about_action)

        # ── 中央ウィジェット ─────────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        self.tabs = QTabWidget()

        self.schedule_tab  = ScheduleTab()
        self.actual_tab    = ActualTab()
        self.gantt_tab     = GanttTab()
        self.monthly_tab   = MonthlyTab()
        self.chart_widget  = ChartWidget()
        self.master_tab    = MasterTab()
        self.history_tab   = HistoryTab()
        self.shared_tab    = SharedTab()

        self.tabs.addTab(self.gantt_tab,    "ガントチャート")
        self.tabs.addTab(self.monthly_tab,  "月次シート")
        self.tabs.addTab(self.schedule_tab, "作業予定")
        self.tabs.addTab(self.actual_tab,   "実績入力")
        self.tabs.addTab(self.chart_widget, "グラフ")
        self.tabs.addTab(self.master_tab,   "マスタ管理")
        self.tabs.addTab(self.history_tab,  "変更履歴")
        self.tabs.addTab(self.shared_tab,   "チーム共有")

        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        # 実績の双方向リアルタイム同期
        self.gantt_tab.actuals_changed.connect(self.actual_tab.refresh)
        self.actual_tab.actuals_changed.connect(self.gantt_tab.refresh)

        self._update_status_bar()
        self._apply_session_ui()

    def _update_window_title(self):
        title = f"{APP_NAME}  v{APP_VERSION}"
        if db.is_admin_session():
            title += f"　―　🔑 管理者　編集対象: {db.get_current_user()}（他のユーザーは参照）"
        elif db.is_db_in_shared_folder():
            title += f"　―　メイン: {db.get_current_user()}（他のユーザーは参照）"
        self.setWindowTitle(title)

    # ── 管理者：編集対象の切り替え ────────────────────────────────────────────

    def _apply_session_ui(self):
        """管理者用ツールバー項目の表示と、編集対象リストを現在の状態に合わせる。"""
        admin = db.is_admin_session()
        for act in (self._admin_sep, self._admin_label_action, self._target_combo_action):
            act.setVisible(admin)
        self._password_action.setVisible(db.get_shared_folder() is not None)
        if not admin:
            return
        folder = db.get_shared_folder()
        users = sorted(f.stem for f in folder.glob("*.db")) if folder else []
        self._target_combo.blockSignals(True)
        self._target_combo.clear()
        self._target_combo.addItems(users)
        self._target_combo.setCurrentText(db.get_current_user())
        self._target_combo.blockSignals(False)

    def _on_target_selected(self, name: str):
        from sync import presence
        if name == db.get_current_user():
            return
        folder = db.get_shared_folder()
        lock = presence.read_lock(folder, name)
        if lock and not presence.is_mine(lock):
            ret = QMessageBox.warning(
                self, "使用中のユーザー",
                f"「{name}」は現在 {lock.get('host', '?')} で開かれています。\n\n"
                "同時に編集すると BOX Drive の同期でどちらかの変更が失われる恐れがあります。\n\n"
                f"それでも「{name}」を編集しますか？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                self._target_combo.setCurrentText(db.get_current_user())
                return
        self._switch_target(name)

    def _switch_target(self, name: str):
        """管理者の編集対象DBを切り替え、全タブを読み直す。"""
        self._stop_presence()
        db.set_session(name, admin=True)
        db.init_db()
        db.clear_undo_history()   # 戻る/進むは前のDBのIDを指すため破棄
        self.gantt_tab.reload_db_settings()
        self._start_presence()
        self._update_window_title()
        self._update_status_bar()
        self._apply_session_ui()
        self._refresh_all(silent=False)
        self.shared_tab.refresh()
        self.statusBar().showMessage(
            f"🔑 管理者　編集対象を「{name}」に切り替えました　│　DB: {db.DB_PATH}", 5000
        )

    # ── パスワード ────────────────────────────────────────────────────────────

    def _change_password(self):
        from sync import auth
        from ui.password_dialogs import PasswordChangeDialog
        folder = db.get_shared_folder()
        if folder is None:
            return

        if db.is_admin_session():
            users = sorted(f.stem for f in folder.glob("*.db"))
            choices = [auth.ADMIN_LABEL] + users
            who, ok = QInputDialog.getItem(
                self, "パスワードの設定",
                "パスワードを設定・変更する対象を選んでください:", choices, 0, False,
            )
            if not ok:
                return
            if who == auth.ADMIN_LABEL:
                dlg = PasswordChangeDialog(
                    self, title="管理者パスワードの変更",
                    verify_current=lambda pw: auth.verify_admin(folder, pw),
                    allow_empty=False, forbidden={auth.DEFAULT_ADMIN_PW},
                )
                if dlg.exec_() == QDialog.Accepted:
                    auth.set_admin_password(folder, dlg.password())
                    QMessageBox.information(self, "完了", "管理者のパスワードを変更しました。")
                return
            # 管理者は現在のパスワードなしでユーザーのパスワードを再設定・解除できる
            dlg = PasswordChangeDialog(
                self, title=f"「{who}」のパスワード設定",
                message=f"管理者として「{who}」のパスワードを設定します。<br>"
                        "空欄のままOKでパスワードを解除します。",
            )
            target = auth.user_db_path(folder, who)
        else:
            target = db.DB_PATH
            has_pw = auth.user_has_password(target)
            dlg = PasswordChangeDialog(
                self, title="パスワードの設定・変更",
                message=f"「{db.get_current_user()}」のログインパスワードを設定します。<br>"
                        "空欄のままOKでパスワードなしになります。",
                verify_current=(lambda pw: auth.verify_user(target, pw)) if has_pw else None,
            )
        if dlg.exec_() != QDialog.Accepted:
            return
        auth.set_user_password(target, dlg.password())
        QMessageBox.information(
            self, "完了",
            "パスワードを設定しました。" if dlg.password() else "パスワードを解除しました。",
        )

    # ── 使用中ロック（他PCに「誰が開いているか」を知らせる）────────────────────

    def _start_presence(self):
        from sync import presence
        if not db.is_db_in_shared_folder():
            return
        self._presence_user = db.get_current_user()
        presence.acquire(db.get_shared_folder(), self._presence_user, admin=db.is_admin_session())
        self._presence_timer = QTimer(self)
        self._presence_timer.timeout.connect(
            lambda: presence.heartbeat(db.get_shared_folder(), self._presence_user))
        self._presence_timer.start(presence.HEARTBEAT_MS)

    def _stop_presence(self):
        from sync import presence
        if self._presence_user is None:
            return
        self._presence_timer.stop()
        presence.release(db.get_shared_folder(), self._presence_user)
        self._presence_user = None

    def _update_status_bar(self):
        user = db.get_current_user()
        if db.is_admin_session():
            user_info = f"🔑 管理者　編集対象: {user}　│　"
        else:
            user_info = f"メイン: {user}　│　" if user and db.is_db_in_shared_folder() else ""
        self.statusBar().showMessage(f"{user_info}DB: {db.DB_PATH}　│　準備完了")

    def _start_auto_refresh(self):
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh)
        self._auto_refresh_timer.start(_AUTO_REFRESH_INTERVAL_MS)

    def _auto_refresh(self):
        """バックグラウンドで静かに全タブを更新し、日付変化時にExcelバックアップを実行する。"""
        try:
            self._refresh_all(silent=True)
        except Exception:
            pass
        self._check_midnight_backup()

    def _check_midnight_backup(self):
        """日付が変わっていれば前日分の Excel バックアップを実行する（深夜0時対応）。"""
        today = _date.today()
        if today <= self._today:
            return
        prev_day = self._today
        self._today = today
        if not excel_backup.is_auto_backup_enabled():
            return
        msgs = []
        try:
            path = excel_backup.backup_day(prev_day)
            msgs.append(f"ガント:{path.name}")
        except Exception as e:
            msgs.append(f"ガント失敗:{e}")
        try:
            path = excel_backup.backup_actuals_month(prev_day.year, prev_day.month)
            if path:
                msgs.append(f"実績:{path.name}")
        except Exception as e:
            msgs.append(f"実績失敗:{e}")
        self.statusBar().showMessage(
            f"DB: {db.DB_PATH}　│　Excel自動保存: {' / '.join(msgs)}", 6000
        )

    def _startup_backup_check(self):
        """起動時チェック: シャットダウン中に0時を過ぎた場合の未実行バックアップを実行する。"""
        today    = _date.today()
        yesterday = today - timedelta(days=1)
        msgs = []
        if excel_backup.needs_startup_backup():
            try:
                path = excel_backup.backup_day(yesterday)
                msgs.append(f"ガント:{path.name}")
            except Exception as e:
                msgs.append(f"ガント失敗:{e}")
        if excel_backup.needs_startup_actual_backup():
            try:
                path = excel_backup.backup_actuals_month(today.year, today.month)
                if path:
                    msgs.append(f"実績:{path.name}")
            except Exception as e:
                msgs.append(f"実績失敗:{e}")
        if msgs:
            self.statusBar().showMessage(
                f"DB: {db.DB_PATH}　│　起動時Excel自動保存: {' / '.join(msgs)}", 8000
            )

    def _manual_refresh(self):
        self._refresh_all(silent=False)
        self.statusBar().showMessage(f"DB: {db.DB_PATH}　│　更新しました", 3000)

    # ── undo / redo ───────────────────────────────────────────────────────────

    def _refresh_all(self, silent=False):
        for tab in (self.gantt_tab, self.monthly_tab, self.schedule_tab,
                    self.actual_tab, self.history_tab):
            if hasattr(tab, 'refresh'):
                tab.refresh()
        if hasattr(self.chart_widget, 'refresh'):
            self.chart_widget.refresh()
        if not silent:
            self._update_undo_btns()

    # ── 共有同期 ──────────────────────────────────────────────────────────────

    def _init_shared_sync(self):
        """起動時に全共有DBを読み込み、ファイル監視スレッドを開始する。"""
        from pathlib import Path
        from sync.reader import load_db_snapshot
        from sync.cache  import shared_cache
        from sync.watcher import DbWatcherThread

        shared_folder = db.get_shared_folder()
        if shared_folder is None or not shared_folder.exists():
            return

        # 起動時：フォルダ内の全DBを一括読み込み
        for db_file in sorted(shared_folder.glob("*.db")):
            snap = load_db_snapshot(db_file)
            if snap:
                shared_cache.update(db_file, snap)
        self.shared_tab.refresh()

        # ファイル監視開始
        self._watcher = DbWatcherThread(shared_folder, parent=self)
        self._watcher.db_updated.connect(self._on_shared_db_updated)
        self._watcher.start()

    def _on_shared_db_updated(self, path_str: str):
        """Boxが他人のDBを同期した際に呼ばれるスロット（メインスレッド実行）。"""
        from pathlib import Path
        from sync.reader import load_db_snapshot
        from sync.cache  import shared_cache

        db_path = Path(path_str)
        snap = load_db_snapshot(db_path)
        if snap:
            shared_cache.update(db_path, snap)
            self.shared_tab.refresh()
            # 他ユーザーのDB更新時のみガントを再描画（自DBの書込み毎に編集中の表を壊さない）
            if db_path.stem != db.DB_PATH.stem:
                self.gantt_tab.refresh()
            user = db.get_current_user()
            user_info = f"ユーザー: {user}　│　" if user else ""
            self.statusBar().showMessage(
                f"{user_info}DB: {db.DB_PATH}　│　{db_path.stem} のデータを更新しました", 4000
            )

    def refresh_shared_view(self):
        """手動/自動更新時に共有タブを再描画する。"""
        self.shared_tab.refresh()

    def _update_undo_btns(self):
        self._undo_action.setEnabled(db.can_undo())
        self._redo_action.setEnabled(db.can_redo())

    def _undo(self):
        if db.do_undo():
            self._refresh_all()
            self.statusBar().showMessage(f"DB: {db.DB_PATH}　│　操作を元に戻しました", 3000)
        self._update_undo_btns()

    def _redo(self):
        if db.do_redo():
            self._refresh_all()
            self.statusBar().showMessage(f"DB: {db.DB_PATH}　│　操作をやり直しました", 3000)
        self._update_undo_btns()

    # ── settings ──────────────────────────────────────────────────────────────

    def _open_settings(self):
        from ui.setup_dialog import DbPathDialog
        dlg = DbPathDialog(self, first_run=False)
        old_folder = db.get_shared_folder()
        if dlg.exec_():
            if db.is_admin_session():
                db.set_session(None, admin=False)   # 設定変更後はこのPCの利用者として開き直す
                db.clear_undo_history()
            if self._presence_user is not None:
                from sync import presence
                self._presence_timer.stop()
                presence.release(old_folder, self._presence_user)
                self._presence_user = None
            try:
                db.init_db()
                self._refresh_all(silent=False)
                self._update_status_bar()
                # 共有同期を再起動（フォルダ変更に対応）
                if self._watcher:
                    self._watcher.stop()
                    self._watcher = None
                self._init_shared_sync()
                self.gantt_tab.reload_db_settings()
                self._start_presence()
                self._update_window_title()
                self._apply_session_ui()
                QMessageBox.information(
                    self, "設定完了",
                    f"データベースの場所を変更しました。\n\n{db.DB_PATH}"
                )
            except Exception as e:
                QMessageBox.critical(self, "DB エラー",
                                     f"新しいパスでデータベースを開けませんでした。\n\n{e}")

    def _open_about(self):
        from ui.about_dialog import AboutDialog
        AboutDialog(self).exec_()

    # ── tab change ────────────────────────────────────────────────────────────

    def _on_tab_changed(self, index):
        self._update_undo_btns()
        tab = self.tabs.widget(index)
        if hasattr(tab, "refresh"):
            tab.refresh()

    # ── window state persistence ──────────────────────────────────────────────

    def _restore_state(self):
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        geometry = s.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
            self._ensure_on_screen()
        state = s.value("windowState")
        if state:
            self.restoreState(state)
        tab_index = s.value("activeTab", 0, type=int)
        if 0 <= tab_index < self.tabs.count():
            self.tabs.setCurrentIndex(tab_index)

    def _ensure_on_screen(self):
        """保存ジオメトリが現在のスクリーン範囲外にある場合、プライマリ画面に収める。"""
        available = QRect()
        for screen in QApplication.screens():
            available = available.united(screen.availableGeometry())
        geo = self.geometry()
        # サイズが画面をはみ出す場合は縮小
        w = min(geo.width(), available.width())
        h = min(geo.height(), available.height())
        if w != geo.width() or h != geo.height():
            self.resize(w, h)
            geo = self.geometry()
        # ウィンドウが有効領域と 100px 以上重なっていなければ中央へ移動
        if available.intersected(geo).width() < 100 or available.intersected(geo).height() < 100:
            primary = QApplication.primaryScreen().availableGeometry()
            geo.moveCenter(primary.center())
            self.move(
                max(primary.left(), min(geo.left(), primary.right()  - geo.width())),
                max(primary.top(),  min(geo.top(),  primary.bottom() - geo.height())),
            )

    # ── Excel バックアップ ────────────────────────────────────────────────────

    def _excel_backup_today(self):
        """今日のデータを手動で Excel に保存する（ガント＋実績）。"""
        today = _date.today()
        msgs, errors = [], []

        try:
            path = excel_backup.backup_day(today)
            msgs.append(f"ガント: {path.name}")
        except Exception as e:
            errors.append(f"ガント失敗: {e}")

        try:
            path = excel_backup.backup_actuals_month(today.year, today.month)
            if path:
                msgs.append(f"実績: {path.name}")
            else:
                msgs.append("実績: データなし")
        except Exception as e:
            errors.append(f"実績失敗: {e}")

        if errors:
            QMessageBox.critical(
                self, "Excel 出力エラー",
                "\n".join(errors),
            )
        else:
            QMessageBox.information(
                self, "Excel 出力完了",
                "保存しました。\n\n" + "\n".join(msgs),
            )

    def _open_excel_settings(self):
        """Excel バックアップ設定ダイアログを開く。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("Excel バックアップ設定")
        dlg.setMinimumWidth(480)
        fl = QFormLayout(dlg)
        fl.setRowWrapPolicy(QFormLayout.WrapLongRows)

        # 自動保存チェックボックス
        auto_chk = QCheckBox("深夜0時に自動保存する（1日1回）")
        auto_chk.setChecked(excel_backup.is_auto_backup_enabled())
        fl.addRow("自動保存:", auto_chk)

        # 保存先フォルダ
        folder_edit = QLineEdit(str(excel_backup.get_backup_dir()))
        folder_edit.setReadOnly(True)
        browse_btn = QPushButton("参照…")

        def _browse():
            d = QFileDialog.getExistingDirectory(
                dlg, "保存先フォルダを選択",
                folder_edit.text(),
                QFileDialog.ShowDirsOnly,
            )
            if d:
                folder_edit.setText(d)

        browse_btn.clicked.connect(_browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(folder_edit)
        folder_row.addWidget(browse_btn)
        fl.addRow("保存先:", folder_row)

        # 説明ラベル
        info = QLabel(
            "【ガントチャートバックアップ】\n"
            "  (保存先)/{year}年{month:02d}月.xlsx　← 1ヶ月 1ブック　/ 1日 1シート\n"
            "【実績バックアップ】\n"
            "  (保存先)/実績_{year}年{month:02d}月.xlsx　← 1ヶ月 1ブック / 上書き保存".format(
                year=_date.today().year, month=_date.today().month
            )
        )
        info.setStyleSheet("color:#555; font-size:11px;")
        fl.addRow(info)

        # ── ガントチャート 今月一括出力 ──
        month_btn = QPushButton(f"ガント: 今月分（{_date.today().year}年{_date.today().month}月）を今すぐ出力")
        month_btn.setToolTip("今月 1 日〜今日の全日分をガントチャートとしてバックアップします")

        def _backup_month():
            try:
                path = excel_backup.backup_month(
                    _date.today().year, _date.today().month
                )
                if path:
                    QMessageBox.information(dlg, "完了", f"今月分（ガント）を保存しました。\n\n{path}")
                else:
                    QMessageBox.information(dlg, "完了", "保存するデータがありませんでした。")
            except Exception as e:
                QMessageBox.critical(dlg, "エラー", str(e))

        month_btn.clicked.connect(_backup_month)
        fl.addRow(month_btn)

        # ── 実績 今月出力 ──
        actual_btn = QPushButton(f"実績: 今月分（{_date.today().year}年{_date.today().month}月）を今すぐ出力")
        actual_btn.setToolTip("今月の実績データを一覧シートに上書き保存します")

        def _backup_actuals():
            try:
                path = excel_backup.backup_actuals_month(
                    _date.today().year, _date.today().month
                )
                if path:
                    QMessageBox.information(dlg, "完了", f"今月分（実績）を保存しました。\n\n{path}")
                else:
                    QMessageBox.information(dlg, "完了", "保存する実績データがありませんでした。")
            except Exception as e:
                QMessageBox.critical(dlg, "エラー", str(e))

        actual_btn.clicked.connect(_backup_actuals)
        fl.addRow(actual_btn)

        # OK / キャンセル
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)

        if dlg.exec_() == QDialog.Accepted:
            excel_backup.set_auto_backup_enabled(auto_chk.isChecked())
            excel_backup.set_backup_dir(Path(folder_edit.text()))

    # ── window state persistence ──────────────────────────────────────────────

    def closeEvent(self, event):
        if self._watcher:
            self._watcher.stop()
        self._stop_presence()
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        s.setValue("geometry", self.saveGeometry())
        s.setValue("windowState", self.saveState())
        s.setValue("activeTab", self.tabs.currentIndex())
        super().closeEvent(event)
