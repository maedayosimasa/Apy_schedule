import sys
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
import database as db
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    font = QFont("Yu Gothic UI", 9)
    font.setStyleHint(QFont.SansSerif)
    app.setFont(font)

    app.setStyleSheet("""
        QMainWindow, QWidget { background-color: #F5F5F5; }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #BDBDBD;
            border-radius: 4px;
            margin-top: 8px;
            padding-top: 4px;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; }
        QTableView {
            background-color: #FFFFFF;
            alternate-background-color: #E8F4FD;
            gridline-color: #E0E0E0;
            selection-background-color: #BBDEFB;
            selection-color: #000000;
        }
        QListView {
            background-color: #FFFFFF;
            alternate-background-color: #E8F4FD;
        }
        QHeaderView::section {
            background-color: #E3F2FD;
            padding: 4px;
            border: none;
            border-right: 1px solid #BDBDBD;
            border-bottom: 1px solid #BDBDBD;
            font-weight: bold;
        }
        QPushButton {
            background-color: #1976D2;
            color: white;
            border: none;
            border-radius: 4px;
            padding: 5px 14px;
            min-width: 64px;
        }
        QPushButton:hover   { background-color: #1565C0; }
        QPushButton:pressed { background-color: #0D47A1; }
        QTabBar::tab {
            background: #E0E0E0;
            padding: 6px 16px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }
        QTabBar::tab:selected { background: #FFFFFF; font-weight: bold; }
        QMenu {
            background-color: #FFFFFF;
            color: #212121;
            border: 1px solid #BDBDBD;
            padding: 2px;
        }
        QMenu::item {
            padding: 5px 20px 5px 12px;
        }
        QMenu::item:selected {
            background-color: #1976D2;
            color: #FFFFFF;
        }
        QMenu::separator {
            height: 1px;
            background: #E0E0E0;
            margin: 3px 6px;
        }
        QCalendarWidget QWidget#qt_calendar_navigationbar {
            background-color: #E3F2FD;
        }
        QCalendarWidget QToolButton {
            color: #000000;
            background-color: transparent;
            font-weight: bold;
            font-size: 11px;
            min-width: 0px;
            padding: 2px 6px;
        }
        QCalendarWidget QToolButton:hover {
            background-color: #BBDEFB;
        }
        QCalendarWidget QSpinBox {
            color: #000000;
            background-color: transparent;
        }
        QCalendarWidget QAbstractItemView:enabled {
            color: #000000;
            selection-background-color: #BBDEFB;
            selection-color: #000000;
        }
        QCalendarWidget QAbstractItemView:disabled {
            color: #9E9E9E;
        }
    """)

    # 初回起動（DB パス未設定）ならセットアップダイアログを表示
    if db.get_db_path() is None:
        from ui.setup_dialog import DbPathDialog
        dlg = DbPathDialog(first_run=True)
        dlg.exec_()  # キャンセルでも続行（EXE と同じフォルダをデフォルト使用）

    try:
        db.init_db()
        db.auto_save_today_snapshot()
        ok, msg = db.check_schema_compatibility()
        if not ok:
            QMessageBox.warning(None, "バージョン互換性の警告", msg)
    except Exception as e:
        ret = QMessageBox.critical(
            None, "DB 初期化エラー",
            f"データベースを開けませんでした。\n\nパス: {db.DB_PATH}\n\nエラー: {e}\n\n"
            "「OK」を押すと EXE と同じフォルダのデータベースを使用します。",
            QMessageBox.Ok | QMessageBox.Cancel,
        )
        if ret == QMessageBox.Ok:
            db.set_db_path(db._DEFAULT_DB_PATH)
            db.refresh_db_path()
            db.init_db()
        else:
            sys.exit(1)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
