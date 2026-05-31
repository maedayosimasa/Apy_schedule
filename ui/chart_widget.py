from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDateEdit, QPushButton,
)
from PyQt5.QtCore import QDate, Qt
from PyQt5.QtGui import QPainter, QColor, QPen, QFont
import database as db

try:
    import matplotlib
    matplotlib.use("Qt5Agg")
    matplotlib.rcParams["font.family"] = ["Yu Gothic", "Meiryo", "MS Gothic", "sans-serif"]
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    _HAS_MPL = True
except Exception:
    _HAS_MPL = False


class ChartWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._setup_ui()
        self.refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── controls ─────────────────────────────────────────────────────────
        cl = QHBoxLayout()
        cl.addWidget(QLabel("期間:"))
        self.from_date = QDateEdit()
        self.from_date.setCalendarPopup(True)
        self.from_date.setDate(QDate.currentDate().addDays(-30))
        cl.addWidget(self.from_date)
        cl.addWidget(QLabel("〜"))
        self.to_date = QDateEdit()
        self.to_date.setCalendarPopup(True)
        self.to_date.setDate(QDate.currentDate().addDays(30))
        cl.addWidget(self.to_date)
        btn = QPushButton("更新")
        btn.clicked.connect(self.refresh)
        cl.addWidget(btn)
        cl.addStretch()
        layout.addLayout(cl)

        # ── chart area ───────────────────────────────────────────────────────
        if _HAS_MPL:
            self._figure = Figure(figsize=(8, 5), tight_layout=True)
            self._canvas = FigureCanvas(self._figure)
            layout.addWidget(self._canvas)
        else:
            self._bar_widget = _FallbackBarChart()
            layout.addWidget(self._bar_widget)
            layout.addWidget(QLabel(
                "※ matplotlib をインストールするとより詳細なグラフが表示されます"
            ))

    def refresh(self):
        date_from = self.from_date.date().toString("yyyy-MM-dd")
        date_to   = self.to_date.date().toString("yyyy-MM-dd")
        data = db.get_summary_by_worker(date_from=date_from, date_to=date_to)

        if _HAS_MPL:
            self._draw_mpl(data)
        else:
            self._bar_widget.set_data(data)

    def _draw_mpl(self, data):
        self._figure.clear()
        ax = self._figure.add_subplot(111)

        if not data:
            ax.text(0.5, 0.5, "データがありません",
                    ha="center", va="center", transform=ax.transAxes, fontsize=14)
            self._canvas.draw()
            return

        names     = [d["name"]      for d in data]
        scheduled = [d["scheduled"] for d in data]
        actual    = [d["actual"]    for d in data]
        x     = range(len(names))
        width = 0.35

        bars1 = ax.bar([i - width / 2 for i in x], scheduled, width,
                       label="予定時間", color="#42A5F5", alpha=0.85)
        bars2 = ax.bar([i + width / 2 for i in x], actual,    width,
                       label="実績時間", color="#66BB6A", alpha=0.85)

        ax.set_xlabel("担当者")
        ax.set_ylabel("時間 (h)")
        ax.set_title("担当者別  予定 vs 実績時間")
        ax.set_xticks(list(x))
        ax.set_xticklabels(names)
        ax.legend()
        ax.grid(axis="y", alpha=0.3)
        ax.set_axisbelow(True)

        for bar in (*bars1, *bars2):
            h = bar.get_height()
            if h > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, h + 0.1,
                        f"{h:.1f}", ha="center", va="bottom", fontsize=8)

        self._canvas.draw()


class _FallbackBarChart(QWidget):
    """Pure-Qt bar chart (no external dependency)."""

    def __init__(self):
        super().__init__()
        self._data = []
        self.setMinimumHeight(320)

    def set_data(self, data):
        self._data = data
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        W, H = self.width(), self.height()
        ML, MR, MT, MB = 55, 20, 20, 50

        painter.fillRect(0, 0, W, H, QColor("#FAFAFA"))

        if not self._data:
            painter.drawText(0, 0, W, H, Qt.AlignCenter, "データがありません")
            return

        max_val = max(max(d["scheduled"], d["actual"]) for d in self._data) or 1
        cw = W - ML - MR
        ch = H - MT - MB
        n  = len(self._data)
        gw = cw / n

        # axes
        painter.setPen(QPen(QColor("#888"), 1))
        painter.drawLine(ML, MT, ML, H - MB)
        painter.drawLine(ML, H - MB, W - MR, H - MB)

        # y-grid & labels
        steps = 5
        for i in range(steps + 1):
            y   = MT + ch * (steps - i) / steps
            val = max_val * i / steps
            painter.setPen(QPen(QColor("#DDD"), 1))
            painter.drawLine(ML, int(y), W - MR, int(y))
            painter.setPen(QPen(QColor("#555"), 1))
            painter.drawText(0, int(y) - 10, ML - 4, 20,
                             Qt.AlignRight | Qt.AlignVCenter, f"{val:.0f}")

        # bars
        bw = gw * 0.28
        for i, d in enumerate(self._data):
            bx = ML + i * gw + gw * 0.12

            def draw_bar(x, value, color):
                bh = int(value / max_val * ch)
                painter.fillRect(int(x), H - MB - bh, int(bw), bh, QColor(color))
                if value > 0:
                    painter.setPen(QPen(QColor("#333"), 1))
                    painter.drawText(int(x), H - MB - bh - 15, int(bw), 14,
                                     Qt.AlignCenter, f"{value:.1f}")

            draw_bar(bx,        d["scheduled"], "#42A5F5")
            draw_bar(bx + bw + 3, d["actual"],   "#66BB6A")

            # name
            painter.setPen(QPen(QColor("#333"), 1))
            painter.drawText(int(ML + i * gw), H - MB + 6, int(gw), 20,
                             Qt.AlignCenter, d["name"])

        # legend
        lx, ly = W - 140, 10
        painter.fillRect(lx, ly,      14, 14, QColor("#42A5F5"))
        painter.drawText(lx + 18, ly, 100, 14, Qt.AlignLeft | Qt.AlignVCenter, "予定時間")
        painter.fillRect(lx, ly + 20, 14, 14, QColor("#66BB6A"))
        painter.drawText(lx + 18, ly + 20, 100, 14, Qt.AlignLeft | Qt.AlignVCenter, "実績時間")
