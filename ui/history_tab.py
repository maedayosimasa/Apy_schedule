from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
    QPushButton, QHeaderView,
)
import database as db
from models import HistoryTableModel
from ui.zoom_mixin import ZoomMixin, ZoomableTableView


class HistoryTab(QWidget, ZoomMixin):
    def __init__(self):
        super().__init__()
        self._init_zoom("zoom_history")
        self._setup_ui()
        self.refresh()
        self._apply_zoom()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        cl = QHBoxLayout()
        cl.addWidget(QLabel("表示件数:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(10, 1000)
        self.limit_spin.setValue(100)
        self.limit_spin.setSingleStep(50)
        cl.addWidget(self.limit_spin)
        btn = QPushButton("更新")
        btn.clicked.connect(self.refresh)
        cl.addWidget(btn)
        self._make_zoom_controls(cl)
        cl.addStretch()
        layout.addLayout(cl)

        self.model = HistoryTableModel()
        self.table = ZoomableTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(ZoomableTableView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        self._register_zoom_table(self.table)

    def refresh(self):
        self.model.refresh(db.get_history(self.limit_spin.value()))

    # ── zoom ─────────────────────────────────────────────────────────────────

    def _apply_zoom(self) -> None:
        self.table.setFont(self._zoom_font())
        self.table.resizeRowsToContents()
        self._update_zoom_label()
