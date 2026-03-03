"""Table view and model for displaying event data in the UI."""

from __future__ import annotations

import logging
from collections.abc import Sequence

import pandas as pd
from PyQt5.QtCore import (
    QAbstractTableModel,
    QEvent,
    QModelIndex,
    QSignalBlocker,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QHelpEvent,
    QKeySequence,
    QPainter,
    QPalette,
    QPixmap,
    QResizeEvent,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDoubleSpinBox,
    QFrame,
    QHeaderView,
    QMenu,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolTip,
)

from vasoanalyzer.ui.formatting.time_format import TimeFormatter, TimeMode, coerce_time_mode
from vasoanalyzer.ui.theme import CURRENT_THEME

log = logging.getLogger(__name__)

# EventRow: (label, time, inner_diameter, outer_diameter | None, avg_pressure | None, set_pressure | None, frame | None)
EventRow = tuple[str, float, float, float | None, float | None, float | None, int | None]
DEFAULT_QMODEL_INDEX = QModelIndex()

STATUS_COLUMN_INDEX = 0
EVENT_COLUMN_INDEX = 1
TIME_COLUMN_INDEX = 2
DEFAULT_EVENT_COLUMN_WIDTH = 220
DEFAULT_REVIEW_STATE = "UNREVIEWED"
STATUS_COLUMN_WIDTH = 28
TIME_COLUMN_WIDTH = 88
ID_COLUMN_WIDTH = 86
OD_COLUMN_WIDTH = 86
PRESSURE_COLUMN_WIDTH = 84
FRAME_COLUMN_WIDTH = 72

HEADER_TOOLTIPS = {
    "Event": "Event label or description",
    "Time (s)": "Timestamp of the event",
    "ID (µm)": "Inner diameter at the event",
    "OD (µm)": "Outer diameter at the event",
    "Avg P (mmHg)": "Average pressure across the interval",
    "Set P (mmHg)": "Commanded set pressure",
    "Trace idx (legacy)": (
        "Imported from the events table; legacy trace/frame hint.\n"
        "Trace/video sync is driven by event time (Time (s))."
    ),
}

COLUMN_KEY_ORDER = (
    "review",
    "event",
    "time",
    "id",
    "od",
    "avg_p",
    "set_p",
)

COLUMN_LABELS = {
    "review": "Review",
    "event": "Event",
    "time": "Time (s)",
    "id": "ID (µm)",
    "od": "OD (µm)",
    "avg_p": "Avg P (mmHg)",
    "set_p": "Set P (mmHg)",
}

COLUMN_KEY_FOR_LABEL = {label: key for key, label in COLUMN_LABELS.items()}
COLUMN_KEY_FOR_LABEL["Time"] = "time"


def build_event_table_column_contract(
    *,
    review_mode: bool,
    show_id: bool,
    show_od: bool,
    show_avg_p: bool,
    show_set_p: bool,
    has_id: bool = True,
    has_od: bool = True,
    has_avg_p: bool = True,
    has_set_p: bool = True,
) -> list[str]:
    """Return ordered column keys for the event table visibility contract."""
    columns: list[str] = []
    if review_mode:
        columns.append("review")
    columns.extend(("event", "time"))
    if show_id and has_id:
        columns.append("id")
    if show_od and has_od:
        columns.append("od")
    if show_avg_p and has_avg_p:
        columns.append("avg_p")
    if show_set_p and has_set_p:
        columns.append("set_p")
    return columns


def column_key_for_header(label: str | None) -> str | None:
    """Map a column header label to its contract key."""
    if not isinstance(label, str):
        return None
    return COLUMN_KEY_FOR_LABEL.get(label)


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


class NumericCellDelegate(QStyledItemDelegate):
    """Delegate for numeric columns with validation and hover states."""

    def __init__(self, parent=None, *, decimals: int = 2) -> None:
        super().__init__(parent)
        self._decimals = max(0, int(decimals))

    def createEditor(self, parent, option: QStyleOptionViewItem, index: QModelIndex):
        """Create a QDoubleSpinBox editor for numeric input."""
        editor = QDoubleSpinBox(parent)
        editor.setDecimals(self._decimals)
        editor.setMinimum(0.0)
        editor.setMaximum(99999.99)
        editor.setFrame(False)
        # Auto-select text on edit start
        editor.selectAll()
        return editor

    def setEditorData(self, editor: QDoubleSpinBox, index: QModelIndex):
        """Load current value into the editor."""
        value = index.data(Qt.EditRole)
        try:
            # Parse display value, removing formatting
            value_str = str(value).replace(",", "").replace("—", "")
            editor.setValue(float(value_str))
        except (TypeError, ValueError):
            editor.setValue(0.0)

    def setModelData(self, editor: QDoubleSpinBox, model: QAbstractTableModel, index: QModelIndex):
        """Save edited value back to the model."""
        editor.interpretText()
        model.setData(index, editor.value(), Qt.EditRole)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        """Custom painting with hover states for editable cells."""
        # Hover state for editable cells
        if option.state & QStyle.State_MouseOver and index.flags() & Qt.ItemIsEditable:
            hover = CURRENT_THEME.get(
                "table_editable_hover", CURRENT_THEME.get("table_hover", "#E5E7EB")
            )
            painter.fillRect(option.rect, QColor(hover))

        # Draw the default content
        super().paint(painter, option, index)


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
        self._time_formatter = TimeFormatter(TimeMode.SECONDS)
        self._time_mode = TimeMode.SECONDS

    def set_time_mode(self, mode: TimeMode | str) -> None:
        resolved = coerce_time_mode(mode)
        if resolved == self._time_mode:
            return
        self._time_mode = resolved
        self._time_formatter.set_mode(resolved)
        if self.rowCount() > 0 and self.columnCount() > TIME_COLUMN_INDEX:
            top_left = self.index(0, TIME_COLUMN_INDEX)
            bottom_right = self.index(self.rowCount() - 1, TIME_COLUMN_INDEX)
            self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole])
        if self.columnCount() > TIME_COLUMN_INDEX:
            self.headerDataChanged.emit(Qt.Horizontal, TIME_COLUMN_INDEX, TIME_COLUMN_INDEX)

    def time_mode(self) -> TimeMode:
        return self._time_mode

    def _display_header(self, header: str) -> str:
        if header == "Time (s)" and self._time_mode != TimeMode.SECONDS:
            return "Time"
        return header

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
                    return self._display_header(header)
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
        col = index.column()

        # Status column (0): not editable via flags (will be handled by click events)
        if col == STATUS_COLUMN_INDEX:
            return base

        # All data columns (Event, Time, ID, OD, Pressures): editable
        if col >= EVENT_COLUMN_INDEX:
            base |= Qt.ItemIsEditable

        return base

    def setData(self, index: QModelIndex, value: object, role: int = Qt.EditRole) -> bool:
        if role not in (Qt.EditRole, Qt.DisplayRole) or not index.isValid():
            return False

        row_idx = index.row()
        col = index.column()

        if not 0 <= row_idx < len(self._rows):
            return False

        # Skip status column
        if col == STATUS_COLUMN_INDEX:
            return False

        # Map display column to tuple index
        tuple_idx = self._column_to_tuple_index(col - 1)  # -1 for status column offset
        if tuple_idx is None:
            return False

        current = list(self._rows[row_idx])

        # Handle Event label column (string)
        if tuple_idx == 0:
            old_label = str(current[0]) if current and current[0] is not None else ""
            new_label = "" if value is None else str(value)
            if new_label == old_label:
                return False
            current[0] = new_label
            self._rows[row_idx] = tuple(current)
            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
            self.label_edited.emit(row_idx, new_label, old_label)
            return True

        # Handle numeric columns (Time, ID, OD, Pressures)
        try:
            new_val = float(value)
            # Round to 2 decimal places for consistency
            new_val = round(new_val, 2)
        except (TypeError, ValueError):
            return False  # Invalid numeric input

        # Get old value
        old_val = current[tuple_idx] if tuple_idx < len(current) else None
        if old_val is not None:
            try:
                if abs(float(old_val) - new_val) < 1e-9:
                    return False  # No change
            except (TypeError, ValueError):
                pass

        # Update the row tuple
        if tuple_idx < len(current):
            current[tuple_idx] = new_val
            self._rows[row_idx] = tuple(current)
            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
            self.value_edited.emit(row_idx, new_val, float(old_val) if old_val is not None else 0.0)
            return True

        return False

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
        # Note: Frame data is still in the row tuple but not displayed as a column
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
    def _column_to_tuple_index(self, column: int) -> int | None:
        """Map display column index to row tuple index for editing.

        Returns the index in the row tuple, or None if column is not editable.
        """
        # Columns: Event(0), Time(1), ID(2), [OD(3)], [AvgP(?)]  [SetP(?)], Frame(last)
        # Row tuple: (label, time, id, od|None, avg_p|None, set_p|None, frame|None)

        if column == 0:  # Event label
            return 0
        if column == 1:  # Time
            return 1
        if column == 2:  # ID
            return 2

        # Build column mapping dynamically
        col_idx = 3

        if self._has_outer:
            if column == col_idx:
                return 3
            col_idx += 1

        if self._has_avg_pressure:
            if column == col_idx:
                return 4
            col_idx += 1

        if self._has_set_pressure:
            if column == col_idx:
                return 5
            col_idx += 1

        # Frame column is not editable
        return None

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
        header_label = None
        data_idx = column - 1
        if 0 <= data_idx < len(self._headers):
            header_label = self._headers[data_idx]

        if isinstance(header_label, str):
            lowered = header_label.lower()
            if "frame" in lowered or "trace idx" in lowered:
                try:
                    fv = float(value)
                    import math
                    if not math.isfinite(fv):
                        return "—"
                    return f"{int(round(fv)):,}"
                except (TypeError, ValueError):
                    return value

        try:
            num = float(value)
        except (TypeError, ValueError):
            return value

        import math
        if not math.isfinite(num):
            return "—"

        if header_label == "Time (s)" or column == TIME_COLUMN_INDEX:
            return self._time_formatter.format(num)
        if column >= TIME_COLUMN_INDEX:  # All numeric columns except status/event label
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
        pix = QPixmap(20, 20)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QColor(color_hex))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(2, 2, 16, 16)
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
    statusChanged = pyqtSignal(int, str)  # row, status

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("EventTable")
        self.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setAlternatingRowColors(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.NoFrame)
        self.setSortingEnabled(True)  # Enable column sorting
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Set up delegates for different column types
        self._event_delegate = EventNameDelegate(self)
        self.setItemDelegateForColumn(EVENT_COLUMN_INDEX, self._event_delegate)

        # Numeric delegate for Time, ID, OD, and Pressure columns
        self._time_delegate = NumericCellDelegate(self, decimals=3)
        self._numeric_delegate = NumericCellDelegate(self, decimals=2)
        self._apply_numeric_delegates()

        self._preferred_event_width = DEFAULT_EVENT_COLUMN_WIDTH

        h_header = self.horizontalHeader()
        h_header.setSectionResizeMode(QHeaderView.Fixed)
        h_header.setMinimumSectionSize(24)
        h_header.setStretchLastSection(False)
        h_header.setDefaultSectionSize(84)
        h_header.setMinimumHeight(28)
        if h_header.count() > EVENT_COLUMN_INDEX:
            h_header.resizeSection(EVENT_COLUMN_INDEX, self._preferred_event_width)
            h_header.setSectionResizeMode(EVENT_COLUMN_INDEX, QHeaderView.Interactive)

        v_header = self.verticalHeader()
        v_header.setSectionResizeMode(QHeaderView.Fixed)
        v_header.setDefaultSectionSize(26)
        v_header.setMinimumWidth(STATUS_COLUMN_WIDTH + 4)
        v_header.setDefaultAlignment(Qt.AlignCenter)

        self.clicked.connect(self._emit_cell_clicked)

    def apply_theme(self) -> None:
        log.debug("[THEME-DEBUG] EventTableWidget.apply_theme called, id(self)=%s", id(self))
        palette = self.palette()
        header_bg = CURRENT_THEME.get(
            "panel_bg", CURRENT_THEME.get("table_bg", palette.color(QPalette.Base).name())
        )
        header_text = CURRENT_THEME.get("text", palette.color(QPalette.Text).name())
        hover = CURRENT_THEME.get("table_hover", CURRENT_THEME.get("button_hover_bg", header_bg))

        base = CURRENT_THEME.get("table_bg", palette.color(QPalette.Base).name())
        alt = CURRENT_THEME.get("alternate_bg", base)
        selection = CURRENT_THEME.get("selection_bg", palette.color(QPalette.Highlight).name())
        selection_text = CURRENT_THEME.get(
            "highlighted_text", palette.color(QPalette.HighlightedText).name()
        )
        grid_base = palette.color(QPalette.Mid)
        grid = CURRENT_THEME.get("table_header_border", grid_base.name())
        header_border = CURRENT_THEME.get(
            "panel_border", CURRENT_THEME.get("table_header_border", grid_base.name())
        )
        row_hover = CURRENT_THEME.get("table_hover", base)

        header = self.horizontalHeader()
        header_style = f"""
            QHeaderView::section {{
                background-color: {header_bg};
                color: {header_text};
                font-weight: 600;
                font-size: 9.5pt;
                padding: 5px 8px;
                border: none;
                border-right: 1px solid {header_border};
                border-bottom: 1px solid {header_border};
            }}
            QHeaderView::section:hover {{
                background-color: {hover};
            }}
            QTableCornerButton::section {{
                background-color: {header_bg};
                border: none;
                border-right: 1px solid {header_border};
                border-bottom: 1px solid {header_border};
            }}
        """
        header.setStyleSheet(header_style)

        v_header = self.verticalHeader()
        v_header_bg = header_bg
        v_header_style = (
            f"QHeaderView::section {{background-color: {v_header_bg}; color: {header_text}; "
            f"font-weight: 500; padding: 0px 5px; border: none; border-right: 1px solid {header_border};}}"
        )
        v_header.setStyleSheet(v_header_style)
        body_style = (
            f"QTableView {{alternate-background-color: {alt}; background-color: {base}; "
            f"gridline-color: {grid}; border: 1px solid {header_border}; border-radius: 3px;}} "
            f"QTableView::item{{padding: 1px 6px;}} "
            f"QTableView::item:hover{{background-color: {row_hover};}} "
            f"QTableView::item:selected{{background-color: {selection}; color: {selection_text};}} "
            f"QTableView::item:selected:hover{{background-color: {selection}; color: {selection_text};}}"
        )
        self.setStyleSheet(body_style)
        log.debug(
            "[THEME-DEBUG] EventTableWidget header_style length=%s body_style length=%s",
            len(header_style),
            len(body_style),
        )

        model = self.model()
        if model and model.columnCount() > 0:
            self._apply_numeric_delegates()
            self.apply_viewport_fit_policy()

    def apply_column_contract(self, column_keys: Sequence[str]) -> None:
        """Show/hide columns to match the column visibility contract."""
        model = self.model()
        if model is None or model.columnCount() == 0:
            return

        visible_keys = set(column_keys)
        h_scroll = self.horizontalScrollBar()
        previous_scroll = h_scroll.value()
        blocker = QSignalBlocker(h_scroll)
        try:
            for col in range(model.columnCount()):
                if col == STATUS_COLUMN_INDEX:
                    self.setColumnHidden(col, "review" not in visible_keys)
                    continue
                header_label = model.headerData(col, Qt.Horizontal, Qt.DisplayRole)
                key = column_key_for_header(header_label)
                if key is None:
                    continue
                self.setColumnHidden(col, key not in visible_keys)
            self.apply_viewport_fit_policy()
            h_scroll.setValue(min(previous_scroll, h_scroll.maximum()))
        finally:
            del blocker

    def _emit_cell_clicked(self, index: QModelIndex) -> None:
        if index.isValid():
            self.cellClicked.emit(index.row(), index.column())

    def keyPressEvent(self, event):
        # Tab/Shift+Tab: Cell navigation
        if event.key() == Qt.Key_Tab or event.key() == Qt.Key_Backtab:
            self._handle_tab_navigation(event.key() == Qt.Key_Backtab)
            event.accept()
            return

        # Ctrl+C: Copy (preserve existing functionality)
        if event.matches(QKeySequence.Copy):
            self._copy_selection_to_clipboard()
            event.accept()
            return

        # F2: Edit current cell (any editable column)
        if event.key() == Qt.Key_F2:
            current = self.currentIndex()
            if current.isValid() and (self.model().flags(current) & Qt.ItemIsEditable):
                self.edit(current)
            event.accept()
            return

        # Shift+Enter: Commit edit and move up
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ShiftModifier:
            if self.state() == QAbstractItemView.EditingState:
                super().keyPressEvent(event)
                if self.state() != QAbstractItemView.EditingState:
                    self._move_selection_up()
            event.accept()
            return

        # Enter: Edit mode or navigate down
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.state() == QAbstractItemView.EditingState:
                super().keyPressEvent(event)
                if self.state() != QAbstractItemView.EditingState:
                    self._move_selection_down()
            else:
                current = self.currentIndex()
                if current.isValid() and (self.model().flags(current) & Qt.ItemIsEditable):
                    self.edit(current)
                else:
                    self._move_selection_down()
            event.accept()
            return

        # Escape: Cancel edit OR clear selection
        if event.key() == Qt.Key_Escape:
            if self.state() == QAbstractItemView.EditingState:
                super().keyPressEvent(event)
            else:
                self.clearSelection()
            event.accept()
            return

        # Delete/Backspace: Delete rows
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

        # Space: Cycle status (when status column focused)
        if event.key() == Qt.Key_Space and not event.modifiers():
            current = self.currentIndex()
            if current.isValid() and current.column() == STATUS_COLUMN_INDEX:
                self._cycle_review_status(current.row())
                event.accept()
                return

        # Default handling for other keys (including Ctrl+A, Ctrl+D, etc.)
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        """Handle mouse clicks, especially for status column interactions."""
        index = self.indexAt(event.pos())
        if index.isValid() and index.column() == STATUS_COLUMN_INDEX:
            if event.button() == Qt.LeftButton:
                self._cycle_review_status(index.row())
                event.accept()
                return
            elif event.button() == Qt.RightButton:
                self._show_status_menu(index.row(), event.globalPos())
                event.accept()
                return
        super().mousePressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_columns_to_viewport()

    def refresh_column_widths(self) -> None:
        model = self.model()
        if not model or model.columnCount() == 0:
            return
        self._fit_columns_to_viewport()

    def _fit_columns_to_viewport(self) -> None:
        """Fit columns to viewport - event column handles stretch."""
        return

    def _apply_column_resize_modes(self) -> None:
        self.apply_viewport_fit_policy()

    def apply_viewport_fit_policy(self) -> None:
        """Sets column resize modes and widths so the table fits the viewport."""
        model = self.model()
        if model is None or model.columnCount() == 0:
            return

        header = self.horizontalHeader()
        header.setStretchLastSection(False)

        event_col = None
        stretch_fallback = None
        for col in range(model.columnCount()):
            if col == STATUS_COLUMN_INDEX:
                header.setSectionResizeMode(col, QHeaderView.Fixed)
                self.setColumnWidth(col, STATUS_COLUMN_WIDTH)
                continue

            header_label = model.headerData(col, Qt.Horizontal, Qt.DisplayRole)
            key = column_key_for_header(header_label)
            if key is None:
                continue

            if not self.isColumnHidden(col) and stretch_fallback is None:
                stretch_fallback = col

            if key == "event":
                event_col = col
                header.setSectionResizeMode(col, QHeaderView.Stretch)
                continue

            header.setSectionResizeMode(col, QHeaderView.Fixed)
            if key == "time":
                self.setColumnWidth(col, TIME_COLUMN_WIDTH)
            elif key == "id":
                self.setColumnWidth(col, ID_COLUMN_WIDTH)
            elif key == "od":
                self.setColumnWidth(col, OD_COLUMN_WIDTH)
            elif key in ("avg_p", "set_p"):
                self.setColumnWidth(col, PRESSURE_COLUMN_WIDTH)

        if event_col is None and stretch_fallback is not None:
            header.setSectionResizeMode(stretch_fallback, QHeaderView.Stretch)

    def _apply_numeric_delegates(self) -> None:
        model = self.model()
        if model is None or model.columnCount() == 0:
            return

        for col in range(model.columnCount()):
            if col in (STATUS_COLUMN_INDEX, EVENT_COLUMN_INDEX):
                continue
            header_label = model.headerData(col, Qt.Horizontal, Qt.DisplayRole)
            if header_label == "Time (s)" or col == TIME_COLUMN_INDEX:
                self.setItemDelegateForColumn(col, self._time_delegate)
            else:
                self.setItemDelegateForColumn(col, self._numeric_delegate)

    def _column_index_for_header(self, label: str) -> int | None:
        model = self.model()
        if model is None:
            return None
        for col in range(model.columnCount()):
            header_label = model.headerData(col, Qt.Horizontal, Qt.DisplayRole)
            if header_label == label:
                return col
        return None

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
        """Legacy method - kept for compatibility. Use _move_selection_down instead."""
        self._move_selection_down()

    def _move_selection_down(self) -> None:
        """Move selection to the cell below in the same column."""
        current = self.currentIndex()
        if current.isValid():
            next_row = min(current.row() + 1, self.model().rowCount() - 1)
            self.setCurrentIndex(self.model().index(next_row, current.column()))

    def _move_selection_up(self) -> None:
        """Move selection to the cell above in the same column."""
        current = self.currentIndex()
        if current.isValid():
            next_row = max(current.row() - 1, 0)
            self.setCurrentIndex(self.model().index(next_row, current.column()))

    def _handle_tab_navigation(self, backwards: bool = False) -> None:
        """Navigate to next/previous editable cell with Tab/Shift+Tab."""
        current = self.currentIndex()
        if not current.isValid():
            # No selection, start at first editable cell
            self.setCurrentIndex(self.model().index(0, EVENT_COLUMN_INDEX))
            return

        model = self.model()
        row, col = current.row(), current.column()

        if backwards:
            # Move left, wrap to previous row
            next_col, next_row = col - 1, row
            while next_row >= 0:
                while next_col >= 0:
                    idx = model.index(next_row, next_col)
                    if model.flags(idx) & Qt.ItemIsEditable:
                        self.setCurrentIndex(idx)
                        return
                    next_col -= 1
                # Wrap to end of previous row
                next_row -= 1
                next_col = model.columnCount() - 1
        else:
            # Move right, wrap to next row
            next_col, next_row = col + 1, row
            while next_row < model.rowCount():
                while next_col < model.columnCount():
                    idx = model.index(next_row, next_col)
                    if model.flags(idx) & Qt.ItemIsEditable:
                        self.setCurrentIndex(idx)
                        return
                    next_col += 1
                # Wrap to start of next row
                next_row += 1
                next_col = 0

    def _cycle_review_status(self, row: int) -> None:
        """Cycle through status states."""
        states = ["UNREVIEWED", "CONFIRMED", "EDITED", "NEEDS_FOLLOWUP"]
        model = self.model()
        current = model._review_states[row] if row < len(model._review_states) else "UNREVIEWED"
        current_idx = states.index(current) if current in states else 0
        next_idx = (current_idx + 1) % len(states)
        self._set_review_status(row, states[next_idx])

    def _set_review_status(self, row: int, status: str) -> None:
        """Set review status for a row."""
        model = self.model()
        if row < len(model._review_states):
            model._review_states[row] = status
        else:
            # Extend review states if needed
            while len(model._review_states) <= row:
                model._review_states.append("UNREVIEWED")
            model._review_states[row] = status

        index = model.index(row, STATUS_COLUMN_INDEX)
        model.dataChanged.emit(index, index, [Qt.DecorationRole, Qt.ToolTipRole])
        self.statusChanged.emit(row, status)

    def _show_status_menu(self, row: int, pos) -> None:
        """Show context menu with status options."""
        menu = QMenu(self)
        menu.addAction("Unreviewed", lambda: self._set_review_status(row, "UNREVIEWED"))
        menu.addAction("Confirmed", lambda: self._set_review_status(row, "CONFIRMED"))
        menu.addAction("Edited", lambda: self._set_review_status(row, "EDITED"))
        menu.addAction("Needs Follow-up", lambda: self._set_review_status(row, "NEEDS_FOLLOWUP"))
        menu.exec_(pos)
