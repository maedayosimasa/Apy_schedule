import sys
from pathlib import Path
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
import database as db
from ui.main_window import MainWindow


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)

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

    # 起動時ダイアログ：「ユーザー選択」で自分（メイン）を選び、他ユーザーは参照で表示。
    # 初回起動・共有フォルダが見つからない場合は「初期設定」タブから始まる。
    # 個人用（DBファイル直接指定）で使っている場合は表示しない（⚙ 設定から変更可）。
    backup_dir   = ""
    new_password = ""
    if not db.is_personal_mode():
        from ui.user_select_dialog import UserSelectDialog
        sel = UserSelectDialog(db.get_shared_folder())
        if sel.exec_() != UserSelectDialog.Accepted:
            sys.exit(0)
        if sel.is_admin():
            # 管理者は設定ファイルの user_name（このPCの利用者）を書き換えない
            db.set_session(sel.selected_user(), admin=True)
        else:
            if sel.selected_user():
                db.set_user_name(sel.selected_user())
            db.refresh_db_path()
        backup_dir   = sel.backup_dir()
        new_password = sel.new_user_password()

    try:
        db.init_db()
        if new_password:   # 新規ユーザー：DB を作成した後でパスワードを保存
            from sync import auth
            auth.set_user_password(db.DB_PATH, new_password)
        if backup_dir:   # Excel バックアップ先はユーザーごとのDBに保存されるため init_db 後に反映
            import excel_backup
            excel_backup.set_backup_dir(Path(backup_dir))
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
