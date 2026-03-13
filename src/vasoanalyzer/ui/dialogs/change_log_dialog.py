"""Dialog for displaying the change log of a sample."""

from __future__ import annotations

import csv
import io
from typing import Any

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QVariant
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from vasoanalyzer.core.audit import (
    CATEGORY_EVENT_ADD,
    CATEGORY_EVENT_DELETE,
    CATEGORY_EVENT_EDIT,
    CATEGORY_EVENT_LABEL,
    CATEGORY_POINT_EDIT,
    CATEGORY_REVIEW_STATUS,
    ChangeEntry,
)

__all__ = ["ChangeLogDialog"]

_COLUMNS = ["Timestamp", "Category", "Description", "User"]

_CATEGORY_COLORS: dict[str, str] = {
    CATEGORY_POINT_EDIT: "#3B82F6",
    CATEGORY_EVENT_EDIT: "#F59E0B",
    CATEGORY_EVENT_LABEL: "#8B5CF6",
    CATEGORY_EVENT_ADD: "#10B981",
    CATEGORY_EVENT_DELETE: "#EF4444",
    CATEGORY_REVIEW_STATUS: "#6366F1",
}

_FILTER_OPTIONS = [
    ("All Changes", None),
    ("Point Edits", CATEGORY_POINT_EDIT),
    ("Event Edits", CATEGORY_EVENT_EDIT),
    ("Event Labels", CATEGORY_EVENT_LABEL),
    ("Events Added", CATEGORY_EVENT_ADD),
    ("Events Deleted", CATEGORY_EVENT_DELETE),
    ("Review Status", CATEGORY_REVIEW_STATUS),
]


class _ChangeLogModel(QAbstractTableModel):
    """Table model for change log entries."""

    def __init__(self, entries: list[ChangeEntry], parent=None) -> None:
        super().__init__(parent)
        self._entries = list(entries)
        self._filtered: list[ChangeEntry] = list(entries)
        self._filter_category: str | None = None

    def set_filter(self, category: str | None) -> None:
        self.beginResetModel()
        self._filter_category = category
        if category is None:
            self._filtered = list(self._entries)
        else:
            self._filtered = [e for e in self._entries if e.category == category]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._filtered)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(_COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._filtered):
            return QVariant()

        entry = self._filtered[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            if col == 1:
                return entry.category_label
            if col == 2:
                return entry.description
            if col == 3:
                return entry.user
            return QVariant()

        if role == Qt.ItemDataRole.ForegroundRole and col == 1:
            color_hex = _CATEGORY_COLORS.get(entry.category)
            if color_hex:
                return QColor(color_hex)

        if role == Qt.ItemDataRole.ToolTipRole and col == 2:
            return entry.description

        return QVariant()

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(_COLUMNS):
                return _COLUMNS[section]
        return QVariant()

    @property
    def filtered_entries(self) -> list[ChangeEntry]:
        return list(self._filtered)


class ChangeLogDialog(QDialog):
    """Display the change log for the current sample."""

    def __init__(
        self,
        entries: list[ChangeEntry],
        sample_name: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        title = "Change Log"
        if sample_name:
            title += f" \u2014 {sample_name}"
        self.setWindowTitle(title)
        self.setMinimumSize(700, 400)
        self.resize(800, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header row
        header = QHBoxLayout()
        header.setSpacing(8)

        count_label = QLabel(f"{len(entries)} change(s) recorded")
        count_label.setStyleSheet("font-weight: bold;")
        header.addWidget(count_label)

        header.addStretch()

        filter_label = QLabel("Filter:")
        header.addWidget(filter_label)

        self._filter_combo = QComboBox()
        for label, _cat in _FILTER_OPTIONS:
            self._filter_combo.addItem(label, _cat)
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        header.addWidget(self._filter_combo)

        layout.addLayout(header)

        # Table
        self._model = _ChangeLogModel(entries, self)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(False)
        self._table.setWordWrap(False)

        h = self._table.horizontalHeader()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self._table, 1)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_row.addWidget(copy_btn)

        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _on_filter_changed(self, index: int) -> None:
        category = self._filter_combo.itemData(index)
        self._model.set_filter(category)

    def _copy_to_clipboard(self) -> None:
        entries = self._model.filtered_entries
        if not entries:
            return
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter="\t")
        writer.writerow(_COLUMNS)
        for entry in entries:
            writer.writerow([
                entry.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                entry.category_label,
                entry.description,
                entry.user,
            ])
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(buf.getvalue())
