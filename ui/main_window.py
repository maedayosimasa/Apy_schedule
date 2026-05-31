from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QTabWidget, QToolBar, QAction,
    QMessageBox, QApplication,
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
import database as db
from version import APP_NAME, APP_VERSION

_AUTO_REFRESH_INTERVAL_MS = 60 * 1000  # 60秒ごとに自動リフレッシュ
_SETTINGS_ORG = "AipySchedule"
_SETTINGS_APP = "MainWindow"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.setMinimumSize(1100, 720)
        self._setup_ui()
        self._restore_state()
        self._start_auto_refresh()

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

        self.tabs.addTab(self.gantt_tab,    "ガントチャート")
        self.tabs.addTab(self.monthly_tab,  "月次シート")
        self.tabs.addTab(self.schedule_tab, "作業予定")
        self.tabs.addTab(self.actual_tab,   "実績入力")
        self.tabs.addTab(self.chart_widget, "グラフ")
        self.tabs.addTab(self.master_tab,   "マスタ管理")
        self.tabs.addTab(self.history_tab,  "変更履歴")

        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        # 実績の双方向リアルタイム同期
        self.gantt_tab.actuals_changed.connect(self.actual_tab.refresh)
        self.actual_tab.actuals_changed.connect(self.gantt_tab.refresh)

        self._update_status_bar()

    def _update_status_bar(self):
        self.statusBar().showMessage(f"DB: {db.DB_PATH}　│　準備完了")

    def _start_auto_refresh(self):
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh)
        self._auto_refresh_timer.start(_AUTO_REFRESH_INTERVAL_MS)

    def _auto_refresh(self):
        """バックグラウンドで静かに全タブを更新する。"""
        try:
            self._refresh_all(silent=True)
        except Exception:
            pass

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
        if dlg.exec_():
            try:
                db.init_db()
                self._refresh_all(silent=False)
                self._update_status_bar()
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

    def closeEvent(self, event):
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        s.setValue("geometry", self.saveGeometry())
        s.setValue("windowState", self.saveState())
        s.setValue("activeTab", self.tabs.currentIndex())
        super().closeEvent(event)
