"""バージョン情報・変更履歴ダイアログ。"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QDialogButtonBox, QFrame,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
import database as db
from version import APP_NAME, APP_VERSION, APP_DATE, DB_SCHEMA_VERSION, CHANGELOG


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("バージョン情報")
        self.setMinimumWidth(500)
        self.setMinimumHeight(480)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── アプリ情報 ──────────────────────────────────────────────────────────
        title_lbl = QLabel(f"{APP_NAME}")
        f = title_lbl.font()
        f.setPointSize(14)
        f.setBold(True)
        title_lbl.setFont(f)
        title_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_lbl)

        ver_lbl = QLabel(f"バージョン  {APP_VERSION}　（{APP_DATE}）")
        ver_lbl.setAlignment(Qt.AlignCenter)
        ver_lbl.setStyleSheet("color: #1565C0; font-size: 12px;")
        layout.addWidget(ver_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # ── DB情報 ─────────────────────────────────────────────────────────────
        try:
            db_ver = db.get_db_schema_version()
        except Exception:
            db_ver = "不明"

        info_rows = [
            ("DB パス",           str(db.DB_PATH)),
            ("DB スキーマバージョン", f"v{db_ver}　（アプリ対応: v{DB_SCHEMA_VERSION}）"),
        ]
        for label, value in info_rows:
            row = QHBoxLayout()
            key_lbl = QLabel(f"{label}：")
            key_lbl.setFixedWidth(160)
            key_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            key_lbl.setStyleSheet("color: #555;")
            val_lbl = QLabel(value)
            val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val_lbl.setWordWrap(True)
            row.addWidget(key_lbl)
            row.addWidget(val_lbl, 1)
            layout.addLayout(row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep2)

        # ── 変更履歴 ─────────────────────────────────────────────────────────
        hist_lbl = QLabel("変更履歴")
        hist_lbl.setStyleSheet("font-weight: bold;")
        layout.addWidget(hist_lbl)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setStyleSheet(
            "QTextBrowser { background: #FAFAFA; border: 1px solid #E0E0E0;"
            " border-radius: 4px; font-size: 11px; }"
        )
        browser.setHtml(_build_changelog_html())
        layout.addWidget(browser, 1)

        # ── 閉じるボタン ──────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)


def _build_changelog_html() -> str:
    lines = []
    for entry in CHANGELOG:
        ver   = entry.get("version", "")
        date_ = entry.get("date", "")
        changes = entry.get("changes", [])
        lines.append(
            f'<p style="margin:6px 0 2px 0;">'
            f'<b style="color:#1565C0;">v{ver}</b>'
            f'<span style="color:#888; margin-left:8px;">（{date_}）</span>'
            f'</p><ul style="margin:0 0 6px 0; padding-left:20px;">'
        )
        for c in changes:
            lines.append(f'<li style="margin:1px 0;">{c}</li>')
        lines.append('</ul>')
    return "".join(lines)
