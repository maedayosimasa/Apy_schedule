from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
    QPushButton, QTableView, QHeaderView,
)
import database as db
from models import HistoryTableModel


class HistoryTab(QWidget):
    def __init__(self):
        super().__init__()
        self._setup_ui()
        self.refresh()

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
        cl.addStretch()
        layout.addLayout(cl)

        self.model = HistoryTableModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

    def refresh(self):
        self.model.refresh(db.get_history(self.limit_spin.value()))
