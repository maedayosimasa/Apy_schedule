from PyQt5.QtWidgets import (
    QLabel, QPushButton, QApplication, QTableView, QTableWidget,
)
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QFont

_SETTINGS_ORG = "AipySchedule"
_SETTINGS_APP = "MainWindow"

_BTN_STYLE = (
    "QPushButton { background-color: #607D8B; color: white; border: none;"
    " border-radius: 3px; padding: 2px 5px; min-width: 0; font-size: 11px; }"
    "QPushButton:hover   { background-color: #546E7A; }"
    "QPushButton:pressed { background-color: #455A64; }"
)


# ── ズーム対応テーブルウィジェット ────────────────────────────────────────────
# QAbstractScrollArea のホイールイベントは viewport のフィルタより先に
# スクロールエリア本体が消費するため、wheelEvent のオーバーライドが唯一確実な方法。

class ZoomableTableView(QTableView):
    """Ctrl+ホイールでズームできる QTableView。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._zoom_owner = None   # ZoomMixin インスタンスをセットする

    def wheelEvent(self, event):
        if self._zoom_owner is not None and (event.modifiers() & Qt.ControlModifier):
            if event.angleDelta().y() > 0:
                self._zoom_owner.zoom_in()
            else:
                self._zoom_owner.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)


class ZoomableTableWidget(QTableWidget):
    """Ctrl+ホイールでズームできる QTableWidget。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._zoom_owner = None

    def wheelEvent(self, event):
        if self._zoom_owner is not None and (event.modifiers() & Qt.ControlModifier):
            if event.angleDelta().y() > 0:
                self._zoom_owner.zoom_in()
            else:
                self._zoom_owner.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)


# ── ZoomMixin ─────────────────────────────────────────────────────────────────

class ZoomMixin:
    """テーブル系タブにフォントサイズズームを付与するミックスイン。

    使い方:
      1. クラスを ZoomMixin と QWidget から多重継承する
      2. __init__ の先頭で _init_zoom(settings_key) を呼ぶ
      3. _setup_ui 内でテーブルに _register_zoom_table(*tables) を呼ぶ
         および _make_zoom_controls(layout) を呼ぶ
      4. _apply_zoom() を実装する
    """

    ZOOM_MIN = -5
    ZOOM_MAX = +5
    _ZOOM_STEP = 0.10   # 1ステップ 10%

    # ── 初期化 ──────────────────────────────────────────────────────────────

    def _init_zoom(self, settings_key: str) -> None:
        self._zoom_level: int = 0
        self._zoom_key: str = settings_key
        self._zoom_base_pt: float = QApplication.instance().font().pointSizeF()
        self._zoom_btn: QPushButton | None = None
        self._zoom_level = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value(
            settings_key, 0, type=int
        )

    # ── UI 部品 ──────────────────────────────────────────────────────────────

    def _make_zoom_controls(self, layout) -> None:
        """既存の QHBoxLayout にズームコントロール（−・%・+）を追加する。"""
        layout.addWidget(QLabel("  倍率:"))

        btn_out = QPushButton("−")
        btn_out.setFixedWidth(26)
        btn_out.setStyleSheet(_BTN_STYLE)
        btn_out.setToolTip("縮小  Ctrl + ホイール下")
        btn_out.clicked.connect(self.zoom_out)
        layout.addWidget(btn_out)

        self._zoom_btn = QPushButton(self._zoom_pct_text())
        self._zoom_btn.setFixedWidth(52)
        self._zoom_btn.setStyleSheet(_BTN_STYLE)
        self._zoom_btn.setToolTip("クリックで 100% にリセット")
        self._zoom_btn.clicked.connect(self.zoom_reset)
        layout.addWidget(self._zoom_btn)

        btn_in = QPushButton("+")
        btn_in.setFixedWidth(26)
        btn_in.setStyleSheet(_BTN_STYLE)
        btn_in.setToolTip("拡大  Ctrl + ホイール上")
        btn_in.clicked.connect(self.zoom_in)
        layout.addWidget(btn_in)

    def _register_zoom_table(self, *tables) -> None:
        """ZoomableTableView / ZoomableTableWidget に自身を登録する。"""
        for t in tables:
            if hasattr(t, '_zoom_owner'):
                t._zoom_owner = self

    # ── ズーム操作 ───────────────────────────────────────────────────────────

    def zoom_in(self) -> None:
        if self._zoom_level < self.ZOOM_MAX:
            self._zoom_level += 1
            self._persist_zoom()
            self._apply_zoom()

    def zoom_out(self) -> None:
        if self._zoom_level > self.ZOOM_MIN:
            self._zoom_level -= 1
            self._persist_zoom()
            self._apply_zoom()

    def zoom_reset(self) -> None:
        if self._zoom_level != 0:
            self._zoom_level = 0
            self._persist_zoom()
            self._apply_zoom()

    # ── 内部ヘルパー ─────────────────────────────────────────────────────────

    def _persist_zoom(self) -> None:
        QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(self._zoom_key, self._zoom_level)

    def _zoom_font(self) -> QFont:
        factor = (1 + self._ZOOM_STEP) ** self._zoom_level
        font = QApplication.instance().font()
        font.setPointSizeF(max(6.0, self._zoom_base_pt * factor))
        return font

    def _zoom_pct_text(self) -> str:
        factor = (1 + self._ZOOM_STEP) ** self._zoom_level
        return f"{int(round(factor * 100))}%"

    def _update_zoom_label(self) -> None:
        if self._zoom_btn is not None:
            self._zoom_btn.setText(self._zoom_pct_text())

    def _apply_zoom(self) -> None:
        raise NotImplementedError("_apply_zoom must be implemented by subclass")

    # ── 旧 API 互換（eventFilter ベース実装のタブが残っている場合用） ──────────
    def _install_wheel_zoom(self, *widgets) -> None:
        self._register_zoom_table(*widgets)
