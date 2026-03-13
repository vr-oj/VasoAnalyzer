from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHeaderView

from vasoanalyzer.ui.event_table import (
    EVENT_COLUMN_INDEX,
    ID_COLUMN_WIDTH,
    OD_COLUMN_WIDTH,
    PRESSURE_COLUMN_WIDTH,
    STATUS_COLUMN_WIDTH,
    TIME_COLUMN_WIDTH,
    EventTableWidget,
)
from vasoanalyzer.ui.event_table_controller import EventTableController


def _column_index_for_label(table: EventTableWidget, label: str) -> int | None:
    model = table.model()
    if model is None:
        return None
    for col in range(model.columnCount()):
        header = model.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        if header == label:
            return col
    return None


def test_event_table_viewport_fit_policy(qt_app):
    table = EventTableWidget()
    controller = EventTableController(table)

    rows = [("Event 1", 1.234, 10.0, 20.0, 5.0, 6.0, 0)]
    controller.set_events(
        rows,
        has_outer_diameter=True,
        has_avg_pressure=True,
        has_set_pressure=True,
        review_states=["UNREVIEWED"],
    )

    table.apply_viewport_fit_policy()
    header = table.horizontalHeader()

    time_col = _column_index_for_label(table, "Time (s)")
    id_col = _column_index_for_label(table, "ID (µm)")
    od_col = _column_index_for_label(table, "OD (µm)")
    avg_p_col = _column_index_for_label(table, "Avg P (mmHg)")
    set_p_col = _column_index_for_label(table, "Set P (mmHg)")

    assert None not in (time_col, id_col, od_col, avg_p_col, set_p_col)
    assert header.sectionResizeMode(EVENT_COLUMN_INDEX) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Fixed
    assert header.sectionResizeMode(time_col) == QHeaderView.ResizeMode.Fixed
    assert header.sectionResizeMode(id_col) == QHeaderView.ResizeMode.Fixed
    assert header.sectionResizeMode(od_col) == QHeaderView.ResizeMode.Fixed
    assert header.sectionResizeMode(avg_p_col) == QHeaderView.ResizeMode.Fixed
    assert header.sectionResizeMode(set_p_col) == QHeaderView.ResizeMode.Fixed

    assert table.columnWidth(0) == STATUS_COLUMN_WIDTH
    assert table.columnWidth(time_col) == TIME_COLUMN_WIDTH
    assert table.columnWidth(id_col) == ID_COLUMN_WIDTH
    assert table.columnWidth(od_col) == OD_COLUMN_WIDTH
    assert table.columnWidth(avg_p_col) == PRESSURE_COLUMN_WIDTH
    assert table.columnWidth(set_p_col) == PRESSURE_COLUMN_WIDTH
