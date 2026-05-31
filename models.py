from datetime import date as _date
from PyQt5.QtCore import Qt, QAbstractTableModel, QModelIndex
from PyQt5.QtGui import QColor
from holidays import get_holiday

STATUS_LABELS = {
    "planned":     "予定",
    "in_progress": "進行中",
    "completed":   "完了",
    "cancelled":   "キャンセル",
}

STATUS_COLORS = {
    "planned":     QColor("#E3F2FD"),
    "in_progress": QColor("#FFF9C4"),
    "completed":   QColor("#E8F5E9"),
    "cancelled":   QColor("#FFEBEE"),
}


class ScheduleTableModel(QAbstractTableModel):
    HEADERS = ["ID", "担当者", "作業名", "予定日", "予定時間(h)", "ステータス", "備考"]
    KEYS    = ["id", "worker_name", "task_title", "scheduled_date",
               "scheduled_hours", "status", "note"]

    def __init__(self, data=None):
        super().__init__()
        self._data = data or []

    def rowCount(self, parent=QModelIndex()):    return len(self._data)
    def columnCount(self, parent=QModelIndex()): return len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._data[index.row()]
        key = self.KEYS[index.column()]

        if role == Qt.DisplayRole:
            val = row.get(key, "")
            if key == "status":
                return STATUS_LABELS.get(val, val)
            return str(val) if val is not None else ""

        if role == Qt.BackgroundRole:
            if key == "scheduled_date":
                try:
                    holiday = get_holiday(_date.fromisoformat(row.get("scheduled_date", "")))
                    if holiday:
                        return QColor("#FFCDD2")
                except ValueError:
                    pass
            return STATUS_COLORS.get(row.get("status", "planned"))

        if role == Qt.ForegroundRole:
            if key == "scheduled_date":
                try:
                    holiday = get_holiday(_date.fromisoformat(row.get("scheduled_date", "")))
                    if holiday:
                        return QColor("#C62828")
                except ValueError:
                    pass
            return None

        if role == Qt.ToolTipRole:
            if key == "scheduled_date":
                try:
                    holiday = get_holiday(_date.fromisoformat(row.get("scheduled_date", "")))
                    if holiday:
                        return holiday
                except ValueError:
                    pass
            return None

        if role == Qt.UserRole:
            return row

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def refresh(self, data):
        self.beginResetModel()
        self._data = data
        self.endResetModel()

    def get_row_data(self, row):
        return self._data[row] if 0 <= row < len(self._data) else None


class ActualTableModel(QAbstractTableModel):
    HEADERS = ["ID", "担当者", "作業名", "実施内容", "実績日", "実績時間(h)"]
    KEYS    = ["id", "worker_name", "task_title", "note", "actual_date", "actual_hours"]

    def __init__(self, data=None):
        super().__init__()
        self._data = data or []

    def rowCount(self, parent=QModelIndex()):    return len(self._data)
    def columnCount(self, parent=QModelIndex()): return len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._data[index.row()]
        key = self.KEYS[index.column()]

        if role == Qt.DisplayRole:
            val = row.get(key, "")
            return str(val) if val is not None else ""

        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignLeft | Qt.AlignTop)

        if role == Qt.BackgroundRole:
            if key == "actual_date":
                try:
                    holiday = get_holiday(_date.fromisoformat(row.get("actual_date", "")))
                    if holiday:
                        return QColor("#FFCDD2")
                except ValueError:
                    pass
            return None

        if role == Qt.ForegroundRole:
            if key == "actual_date":
                try:
                    holiday = get_holiday(_date.fromisoformat(row.get("actual_date", "")))
                    if holiday:
                        return QColor("#C62828")
                except ValueError:
                    pass
            return None

        if role == Qt.ToolTipRole:
            if key == "actual_date":
                try:
                    holiday = get_holiday(_date.fromisoformat(row.get("actual_date", "")))
                    if holiday:
                        return holiday
                except ValueError:
                    pass
            return None

        if role == Qt.UserRole:
            return row

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def refresh(self, data):
        self.beginResetModel()
        self._data = data
        self.endResetModel()

    def get_row_data(self, row):
        return self._data[row] if 0 <= row < len(self._data) else None


class HistoryTableModel(QAbstractTableModel):
    HEADERS = ["ID", "テーブル", "レコードID", "操作", "変更前", "変更後", "日時"]
    KEYS    = ["id", "table_name", "record_id", "action",
               "old_values", "new_values", "changed_at"]

    def __init__(self, data=None):
        super().__init__()
        self._data = data or []

    def rowCount(self, parent=QModelIndex()):    return len(self._data)
    def columnCount(self, parent=QModelIndex()): return len(self.HEADERS)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.DisplayRole:
            val = self._data[index.row()].get(self.KEYS[index.column()], "")
            return str(val) if val is not None else ""
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def refresh(self, data):
        self.beginResetModel()
        self._data = data
        self.endResetModel()
