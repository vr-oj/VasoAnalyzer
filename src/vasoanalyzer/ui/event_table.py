"""Table view and model for displaying event data in the UI."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
from PyQt5.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QTableView,
)

from vasoanalyzer.ui.theme import CURRENT_THEME

EventRow = tuple[str, float, float, float | None, int | None]
DEFAULT_QMODEL_INDEX = QModelIndex()


class EventTableModel(QAbstractTableModel):
    """Model backing the event table view with editable ID values."""

    value_edited = pyqtSignal(int, float, float)
    structure_changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[tuple] = []
        self._has_outer = False
        self._headers: list[str] = []

    # Qt model API -----------------------------------------------------
    def rowCount(self, parent: QModelIndex = DEFAULT_QMODEL_INDEX) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = DEFAULT_QMODEL_INDEX) -> int:
        return 0 if parent.isValid() else len(self._headers)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row_idx = index.row()
        col = index.column()
        if row_idx >= len(self._rows) or col >= len(self._headers):
            return None

        raw_value = self._value_at(row_idx, col)

        if role == Qt.DisplayRole:
            return self._format_display(col, raw_value)
        if role == Qt.EditRole:
            return "" if raw_value is None else str(raw_value)
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemIsEnabled
        base = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if index.column() == 2:  # ID (µm)
            base |= Qt.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value: object, role: int = Qt.EditRole) -> bool:
        if role not in (Qt.EditRole, Qt.DisplayRole) or not index.isValid():
            return False
        if index.column() != 2:
            return False

        row_idx = index.row()
        if row_idx >= len(self._rows):
            return False

        try:
            new_val = round(float(str(value)), 2)
        except (TypeError, ValueError):
            return False

        current = list(self._rows[row_idx])
        old_val = float(current[2]) if current[2] is not None else 0.0
        current[2] = new_val
        self._rows[row_idx] = tuple(current)
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        self.value_edited.emit(row_idx, new_val, old_val)
        return True

    # Public helpers ---------------------------------------------------
    def set_events(self, rows: Sequence[tuple], *, has_outer_diameter: bool) -> None:
        self.beginResetModel()
        self._rows = [tuple(row) for row in rows]
        self._has_outer = has_outer_diameter
        headers = ["Event", "Time (s)", "ID (µm)"]
        if has_outer_diameter:
            headers.append("OD (µm)")
        headers.append("Frame")
        self._headers = headers
        self.endResetModel()
        self.structure_changed.emit()

    def clear(self) -> None:
        self.set_events([], has_outer_diameter=False)

    def rows(self) -> list[tuple]:
        return list(self._rows)

    def has_outer(self) -> bool:
        return self._has_outer

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self._rows, columns=self._headers)

    def insert_row(self, index: int, row: tuple) -> None:
        self.beginInsertRows(QModelIndex(), index, index)
        self._rows.insert(index, tuple(row))
        self.endInsertRows()

    def append_row(self, row: tuple) -> None:
        self.insert_row(len(self._rows), row)

    def remove_row(self, index: int) -> tuple:
        self.beginRemoveRows(QModelIndex(), index, index)
        removed = self._rows.pop(index)
        self.endRemoveRows()
        return removed

    def update_row(self, index: int, row: tuple) -> None:
        if not 0 <= index < len(self._rows):
            return
        self._rows[index] = tuple(row)
        left = self.index(index, 0)
        right = self.index(index, self.columnCount() - 1)
        self.dataChanged.emit(left, right, [Qt.DisplayRole, Qt.EditRole])

    # Internal helpers -------------------------------------------------
    def _value_at(self, row_idx: int, column: int):
        row = self._rows[row_idx]
        if self._has_outer:
            return row[column]
        if column <= 2:
            return row[column]
        # Frame when no outer diameter present
        return row[3] if len(row) > 3 else None

    def _format_display(self, column: int, value):
        if column == 0:  # Event label
            return value
        if value is None:
            return "—"
        is_frame_column = (column == 4 and self._has_outer) or (column == 3 and not self._has_outer)
        if is_frame_column:
            try:
                return f"{int(round(float(value))):,}"
            except (TypeError, ValueError):
                return value

        try:
            num = float(value)
        except (TypeError, ValueError):
            return value

        if column in (1, 2) or (self._has_outer and column == 3):
            return f"{num:,.2f}"

        return f"{num:,}"


class EventTableWidget(QTableView):
    """QTableView wrapper with styling helpers for event data."""

    cellClicked = pyqtSignal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("EventTable")
        self.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.NoFrame)

        h_header = self.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        h_header.setMinimumSectionSize(70)
        h_header.setStretchLastSection(True)
        h_header.setDefaultSectionSize(110)
        h_header.setMinimumHeight(24)

        v_header = self.verticalHeader()
        v_header.setSectionResizeMode(QHeaderView.Fixed)
        v_header.setDefaultSectionSize(24)
        v_header.setMinimumWidth(36)
        v_header.setDefaultAlignment(Qt.AlignCenter)

        self.clicked.connect(self._emit_cell_clicked)

    def apply_theme(self) -> None:
        header_bg = CURRENT_THEME.get("button_active_bg", CURRENT_THEME["button_bg"])
        header_text = CURRENT_THEME["text"]
        base = CURRENT_THEME["table_bg"]
        alt = CURRENT_THEME["alternate_bg"]
        selection = CURRENT_THEME["selection_bg"]
        grid = CURRENT_THEME["grid_color"]

        header = self.horizontalHeader()
        header.setStyleSheet(
            f"QHeaderView::section {{background-color: {header_bg}; color: {header_text}; "
            "font-weight: 600; padding: 4px 8px; border: none; border-top-left-radius: 6px; "
            "border-top-right-radius: 6px;}"
        )
        v_header = self.verticalHeader()
        v_header_bg = CURRENT_THEME.get("button_active_bg", CURRENT_THEME["button_bg"])
        v_header.setStyleSheet(
            f"QHeaderView::section {{background-color: {v_header_bg}; color: {header_text}; "
            "font-weight: 500; padding: 0px 6px; border: none;}"
        )
        self.setStyleSheet(
            f"QTableView {{alternate-background-color: {alt}; background-color: {base}; "
            f"gridline-color: {grid}; border: none;}} "
            f"QTableView::item:selected{{background-color: {selection}; color: {header_text};}}"
        )

        model = self.model()
        if model and model.columnCount() > 0:
            for col in range(model.columnCount()):
                header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
            header.setStretchLastSection(True)
            self.refresh_column_widths()

    def _emit_cell_clicked(self, index: QModelIndex) -> None:
        if index.isValid():
            self.cellClicked.emit(index.row(), index.column())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_columns_to_viewport()

    def refresh_column_widths(self) -> None:
        model = self.model()
        if not model or model.columnCount() == 0:
            return

        self.resizeColumnsToContents()
        self._fit_columns_to_viewport()

    def _fit_columns_to_viewport(self) -> None:
        model = self.model()
        if not model or model.columnCount() == 0:
            return

        viewport_width = self.viewport().width()
        if viewport_width <= 0:
            return

        total_width = sum(self.columnWidth(col) for col in range(model.columnCount()))
        if total_width >= viewport_width:
            return

        remaining = viewport_width - total_width
        last_col = model.columnCount() - 1
        self.setColumnWidth(last_col, self.columnWidth(last_col) + remaining)
