"""Table view and model for displaying event data in the UI."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
from PyQt5.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QHelpEvent, QKeySequence, QPainter, QPixmap, QResizeEvent
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolTip,
)

from vasoanalyzer.ui.theme import CURRENT_THEME

# EventRow: (label, time, inner_diameter, outer_diameter | None, avg_pressure | None, set_pressure | None, frame | None)
EventRow = tuple[str, float, float, float | None, float | None, float | None, int | None]
DEFAULT_QMODEL_INDEX = QModelIndex()

STATUS_COLUMN_INDEX = 0
EVENT_COLUMN_INDEX = 1
DEFAULT_EVENT_COLUMN_WIDTH = 220
DEFAULT_REVIEW_STATE = "UNREVIEWED"

HEADER_TOOLTIPS = {
    "Event": "Event label or description",
    "Time (s)": "Timestamp of the event",
    "ID (µm)": "Inner diameter at the event",
    "OD (µm)": "Outer diameter at the event",
    "Avg P (mmHg)": "Average pressure across the interval",
    "Set P (mmHg)": "Commanded set pressure",
    "Frame": "Frame index if available",
}


class EventNameDelegate(QStyledItemDelegate):
    """Delegate for rendering long event labels with elided text and tooltips."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        text = index.data(Qt.DisplayRole)
        if text is None:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        metrics = opt.fontMetrics
        opt.text = metrics.elidedText(str(text), Qt.ElideRight, opt.rect.width())
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter)

    def helpEvent(
        self,
        event: QHelpEvent,
        view: QAbstractItemView,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> bool:
        if event.type() == QEvent.ToolTip:
            text = index.data(Qt.DisplayRole)
            if text:
                QToolTip.showText(event.globalPos(), str(text), view)
                return True
        return super().helpEvent(event, view, option, index)


class EventTableModel(QAbstractTableModel):
    """Model backing the event table view with editable event labels."""

    value_edited = pyqtSignal(int, float, float)
    label_edited = pyqtSignal(int, str, str)
    structure_changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[tuple] = []
        self._has_outer = False
        self._headers: list[str] = []
        self._review_states: list[str] = []
        self._status_icons: dict[str, QPixmap] = {}

    # Qt model API -----------------------------------------------------
    def rowCount(self, parent: QModelIndex = DEFAULT_QMODEL_INDEX) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = DEFAULT_QMODEL_INDEX) -> int:
        if parent.isValid():
            return 0
        if not self._headers:
            return 0
        # Extra leading status column
        return len(self._headers) + 1

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if orientation == Qt.Horizontal and 0 <= section < self.columnCount():
            if section == STATUS_COLUMN_INDEX:
                if role == Qt.DisplayRole:
                    return " "
                if role == Qt.ToolTipRole:
                    return "Review status"
                if role == Qt.TextAlignmentRole:
                    return Qt.AlignHCenter | Qt.AlignVCenter
                return None

            data_idx = section - 1
            if 0 <= data_idx < len(self._headers):
                header = self._headers[data_idx]
                if role == Qt.DisplayRole:
                    return header
                if role == Qt.ToolTipRole:
                    return HEADER_TOOLTIPS.get(header)
                if role == Qt.TextAlignmentRole:
                    if section == EVENT_COLUMN_INDEX:
                        return Qt.AlignLeft | Qt.AlignVCenter
                    return Qt.AlignHCenter | Qt.AlignVCenter
                return None
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row_idx = index.row()
        col = index.column()
        if row_idx >= len(self._rows) or col >= self.columnCount():
            return None

        if col == STATUS_COLUMN_INDEX:
            state = self._review_states[row_idx] if row_idx < len(self._review_states) else None
            if role == Qt.DecorationRole:
                return self._status_icon_for(state)
            if role == Qt.ToolTipRole:
                return self._status_tooltip(state)
            if role == Qt.DisplayRole:
                return ""
            if role == Qt.TextAlignmentRole:
                return Qt.AlignCenter
            return None

        raw_value = self._value_at(row_idx, col - 1)

        if role == Qt.DisplayRole:
            return self._format_display(col, raw_value)
        if role == Qt.EditRole:
            return "" if raw_value is None else str(raw_value)
        if role == Qt.TextAlignmentRole:
            if col == EVENT_COLUMN_INDEX:
                return Qt.AlignVCenter | Qt.AlignLeft
            return Qt.AlignVCenter | Qt.AlignRight
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemIsEnabled
        base = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if index.column() == EVENT_COLUMN_INDEX:
            base |= Qt.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value: object, role: int = Qt.EditRole) -> bool:
        if role not in (Qt.EditRole, Qt.DisplayRole) or not index.isValid():
            return False
        if index.column() != EVENT_COLUMN_INDEX:
            return False

        row_idx = index.row()
        if not 0 <= row_idx < len(self._rows):
            return False

        current = list(self._rows[row_idx])
        old_label = str(current[0]) if current and current[0] is not None else ""
        new_label = "" if value is None else str(value)
        if new_label == old_label:
            return False

        current[0] = new_label
        self._rows[row_idx] = tuple(current)
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
        self.label_edited.emit(row_idx, new_label, old_label)
        return True

    # Public helpers ---------------------------------------------------
    def set_events(
        self,
        rows: Sequence[tuple],
        *,
        has_outer_diameter: bool,
        has_avg_pressure: bool = False,
        has_set_pressure: bool = False,
        review_states: Sequence[str] | None = None,
    ) -> None:
        self.beginResetModel()
        self._rows = [tuple(row) for row in rows]
        self._has_outer = has_outer_diameter
        self._has_avg_pressure = has_avg_pressure
        self._has_set_pressure = has_set_pressure
        headers = ["Event", "Time (s)", "ID (µm)"]
        if has_outer_diameter:
            headers.append("OD (µm)")
        if has_avg_pressure:
            headers.append("Avg P (mmHg)")
        if has_set_pressure:
            headers.append("Set P (mmHg)")
        headers.append("Frame")
        self._headers = headers
        self.set_review_states(list(review_states or []), suppress_layout=True)
        self.endResetModel()
        self.structure_changed.emit()

    def clear(self) -> None:
        self.set_events([], has_outer_diameter=False)

    def rows(self) -> list[tuple]:
        return list(self._rows)

    def has_outer(self) -> bool:
        return self._has_outer

    def review_states(self) -> list[str]:
        return list(self._review_states)

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

    def set_review_states(self, review_states: list[str] | None, *, suppress_layout: bool = False):
        target_len = len(self._rows)
        incoming = list(review_states or [])
        if len(incoming) < target_len:
            incoming.extend([DEFAULT_REVIEW_STATE] * (target_len - len(incoming)))
        elif len(incoming) > target_len:
            incoming = incoming[:target_len]
        # Normalize entries
        self._review_states = [
            state if isinstance(state, str) and state.strip() else DEFAULT_REVIEW_STATE
            for state in incoming
        ]
        if not suppress_layout:
            top_left = self.index(0, STATUS_COLUMN_INDEX) if self.rowCount() else QModelIndex()
            bottom_right = (
                self.index(self.rowCount() - 1, STATUS_COLUMN_INDEX)
                if self.rowCount()
                else QModelIndex()
            )
            if top_left.isValid() and bottom_right.isValid():
                self.dataChanged.emit(top_left, bottom_right, [Qt.DecorationRole, Qt.ToolTipRole])

    # Internal helpers -------------------------------------------------
    def _value_at(self, row_idx: int, column: int):
        """Map display column to row tuple index."""
        row = self._rows[row_idx]
        if len(row) < 3:
            return None

        # Columns: Event(0), Time(1), ID(2), [OD(3)], [AvgP(?)]  [SetP(?)], Frame(last)
        # Row tuple: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)

        if column == 0:  # Event label
            return row[0]
        if column == 1:  # Time
            return row[1]
        if column == 2:  # ID
            return row[2]

        # Build column mapping dynamically
        col_idx = 3

        if self._has_outer:
            if column == col_idx:
                return row[3] if len(row) > 3 else None
            col_idx += 1

        if self._has_avg_pressure:
            if column == col_idx:
                return row[4] if len(row) > 4 else None
            col_idx += 1

        if self._has_set_pressure:
            if column == col_idx:
                return row[5] if len(row) > 5 else None
            col_idx += 1

        # Last column is always Frame
        if column == col_idx:
            frame_idx = len(row) - 1
            if frame_idx < 0:
                return None
            return row[frame_idx] if frame_idx < len(row) else None

        return None

    def _format_display(self, column: int, value):
        if column == EVENT_COLUMN_INDEX:  # Event label
            return value
        if value is None:
            return "—"

        # Determine if this is the frame column (always last)
        last_col_idx = self.columnCount() - 1
        is_frame_column = column == last_col_idx

        if is_frame_column:
            try:
                return f"{int(round(float(value))):,}"
            except (TypeError, ValueError):
                return value

        try:
            num = float(value)
        except (TypeError, ValueError):
            return value

        # Time, diameter, and pressure columns get 2 decimal places
        if column >= 2:  # All numeric columns except status/event label
            return f"{num:,.2f}"

        return f"{num:,}"

    def _status_icon_for(self, state: str | None) -> QPixmap:
        label = self._status_label(state)
        if label in self._status_icons:
            return self._status_icons[label]

        color_map = {
            "UNREVIEWED": "#9CA3AF",  # gray
            "CONFIRMED": "#10B981",  # green
            "EDITED": "#F59E0B",  # amber
            "NEEDS_FOLLOWUP": "#EF4444",  # red
        }
        color_hex = (
            color_map.get(label.upper(), color_map["UNREVIEWED"])
            if isinstance(label, str)
            else color_map["UNREVIEWED"]
        )
        pix = QPixmap(12, 12)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QColor(color_hex))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(1, 1, 10, 10)
        painter.end()
        self._status_icons[label] = pix
        return pix

    @staticmethod
    def _status_label(state: str | None) -> str:
        if not isinstance(state, str) or not state.strip():
            return DEFAULT_REVIEW_STATE
        normalized = state.strip().upper().replace(" ", "_").replace("-", "_")
        return normalized or DEFAULT_REVIEW_STATE

    def _status_tooltip(self, state: str | None) -> str:
        label = self._status_label(state)
        friendly = {
            "UNREVIEWED": "Unreviewed",
            "CONFIRMED": "Confirmed",
            "EDITED": "Edited",
            "NEEDS_FOLLOWUP": "Needs follow-up",
        }
        return friendly.get(label, "Unreviewed")


class EventTableWidget(QTableView):
    """QTableView wrapper with styling helpers for event data."""

    cellClicked = pyqtSignal(int, int)
    rowsDeletionRequested = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("EventTable")
        self.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setAlternatingRowColors(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.NoFrame)
        self._event_delegate = EventNameDelegate(self)
        self.setItemDelegateForColumn(EVENT_COLUMN_INDEX, self._event_delegate)
        self._preferred_event_width = DEFAULT_EVENT_COLUMN_WIDTH

        h_header = self.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        h_header.setMinimumSectionSize(40)
        h_header.setStretchLastSection(False)
        h_header.setDefaultSectionSize(110)
        h_header.setMinimumHeight(24)
        if h_header.count() > EVENT_COLUMN_INDEX:
            h_header.resizeSection(EVENT_COLUMN_INDEX, self._preferred_event_width)
            h_header.setSectionResizeMode(EVENT_COLUMN_INDEX, QHeaderView.Interactive)

        v_header = self.verticalHeader()
        v_header.setSectionResizeMode(QHeaderView.Fixed)
        v_header.setDefaultSectionSize(24)
        v_header.setMinimumWidth(36)
        v_header.setDefaultAlignment(Qt.AlignCenter)

        self.clicked.connect(self._emit_cell_clicked)

    def apply_theme(self) -> None:
        print(f"[THEME-DEBUG] EventTableWidget.apply_theme called, id(self)={id(self)}")
        header_bg = CURRENT_THEME.get("button_active_bg", CURRENT_THEME["button_bg"])
        header_text = CURRENT_THEME["text"]
        base = CURRENT_THEME["table_bg"]
        alt = CURRENT_THEME["alternate_bg"]
        selection = CURRENT_THEME["selection_bg"]
        grid = CURRENT_THEME["grid_color"]

        header = self.horizontalHeader()
        header_style = (
            f"QHeaderView::section {{background-color: {header_bg}; color: {header_text}; "
            "font-weight: 600; padding: 4px 8px; border: none; border-top-left-radius: 6px; "
            "border-top-right-radius: 6px;}"
        )
        header.setStyleSheet(header_style)
        v_header = self.verticalHeader()
        v_header_bg = CURRENT_THEME.get("button_active_bg", CURRENT_THEME["button_bg"])
        v_header_style = (
            f"QHeaderView::section {{background-color: {v_header_bg}; color: {header_text}; "
            "font-weight: 500; padding: 0px 6px; border: none;}"
        )
        v_header.setStyleSheet(v_header_style)
        body_style = (
            f"QTableView {{alternate-background-color: {alt}; background-color: {base}; "
            f"gridline-color: {grid}; border: none;}} "
            f"QTableView::item:selected{{background-color: {selection}; color: {header_text};}}"
        )
        self.setStyleSheet(body_style)
        print(
            f"[THEME-DEBUG] EventTableWidget header_style length={len(header_style)} body_style length={len(body_style)}"
        )

        model = self.model()
        if model and model.columnCount() > 0:
            self._apply_column_resize_modes()
            self.refresh_column_widths()

    def _emit_cell_clicked(self, index: QModelIndex) -> None:
        if index.isValid():
            self.cellClicked.emit(index.row(), index.column())

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            self._copy_selection_to_clipboard()
            event.accept()
            return

        if event.key() == Qt.Key_F2:
            self._start_editing_event_column()
            event.accept()
            return

        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.state() == QAbstractItemView.EditingState:
                super().keyPressEvent(event)
                if self.state() != QAbstractItemView.EditingState:
                    self._move_to_next_event_cell()
            else:
                self._start_editing_event_column()
            event.accept()
            return

        if (
            event.key() in (Qt.Key_Delete, Qt.Key_Backspace)
            and self.state() != QAbstractItemView.EditingState
        ):
            selection = self.selectionModel()
            if selection is not None:
                rows = {index.row() for index in selection.selectedRows()}
                if rows:
                    self.rowsDeletionRequested.emit(sorted(rows))
                    event.accept()
                    return
        super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_columns_to_viewport()

    def refresh_column_widths(self) -> None:
        model = self.model()
        if not model or model.columnCount() == 0:
            return

        header = self.horizontalHeader()
        for col in range(model.columnCount()):
            mode = header.sectionResizeMode(col)
            if mode == QHeaderView.ResizeToContents:
                self.resizeColumnToContents(col)
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

    def _apply_column_resize_modes(self) -> None:
        model = self.model()
        if not model or model.columnCount() == 0:
            return

        header = self.horizontalHeader()
        header.setStretchLastSection(False)

        important_numeric = {"ID (µm)", "OD (µm)", "Avg P (mmHg)"}
        trailing = {"Set P (mmHg)", "Frame"}

        for col in range(model.columnCount()):
            title = model.headerData(col, Qt.Horizontal, Qt.DisplayRole) or ""
            if col == STATUS_COLUMN_INDEX:
                header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
                header.resizeSection(col, max(26, header.sectionSize(col)))
            elif col == EVENT_COLUMN_INDEX:
                header.setSectionResizeMode(col, QHeaderView.Interactive)
                preferred_width = max(
                    self._preferred_event_width,
                    header.sectionSize(col),
                    header.minimumSectionSize(),
                )
                header.resizeSection(col, preferred_width)
            elif title in important_numeric:
                header.setSectionResizeMode(col, QHeaderView.Interactive)
                header.resizeSection(col, max(90, header.sectionSize(col)))
            elif title == "Time (s)":
                header.setSectionResizeMode(col, QHeaderView.Interactive)
                header.resizeSection(col, max(80, header.sectionSize(col)))
            elif title in trailing:
                header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

    def _copy_selection_to_clipboard(self) -> None:
        indexes = self.selectedIndexes()
        if not indexes:
            return

        indexes = sorted(indexes, key=lambda idx: (idx.row(), idx.column()))
        rows = [idx.row() for idx in indexes]
        cols = [idx.column() for idx in indexes]
        min_row, max_row = min(rows), max(rows)
        min_col, max_col = min(cols), max(cols)
        selected_map = {(idx.row(), idx.column()): idx for idx in indexes}

        lines: list[str] = []
        for row in range(min_row, max_row + 1):
            values: list[str] = []
            for col in range(min_col, max_col + 1):
                idx = selected_map.get((row, col))
                data = idx.data(Qt.DisplayRole) if idx is not None else ""
                if data is None:
                    data = ""
                values.append(str(data))
            lines.append("\t".join(values))

        QApplication.clipboard().setText("\n".join(lines))

    def _start_editing_event_column(self) -> None:
        model = self.model()
        selection = self.selectionModel()
        if model is None or selection is None:
            return
        if model.rowCount() == 0:
            return
        current = selection.currentIndex()
        if not current.isValid():
            current = model.index(0, EVENT_COLUMN_INDEX)
        elif current.column() != EVENT_COLUMN_INDEX:
            current = model.index(current.row(), EVENT_COLUMN_INDEX)
        self.setCurrentIndex(current)
        self.edit(current)

    def _move_to_next_event_cell(self) -> None:
        model = self.model()
        selection = self.selectionModel()
        if model is None or selection is None:
            return
        current = selection.currentIndex()
        if not current.isValid():
            return
        next_row = min(current.row() + 1, model.rowCount() - 1)
        next_index = model.index(next_row, EVENT_COLUMN_INDEX)
        if next_index.isValid():
            self.setCurrentIndex(next_index)
