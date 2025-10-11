"""Controller coordinating the event table model and view."""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

import pandas as pd
from PyQt5.QtCore import QObject, pyqtSignal

from .event_table import EventRow, EventTableModel, EventTableWidget


class EventTableController(QObject):
    """Manage event table data mutations and view refreshes."""

    rows_changed = pyqtSignal()
    cell_edited = pyqtSignal(int, float, float)

    def __init__(self, table: EventTableWidget, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._table = table
        self._model = EventTableModel(table)
        self._table.setModel(self._model)
        self._table.apply_theme()

        self._model.value_edited.connect(self.cell_edited.emit)
        self._model.structure_changed.connect(self._table.apply_theme)
        self._model.dataChanged.connect(lambda *_: self._table.refresh_column_widths())
        self._model.rowsInserted.connect(lambda *_: self._table.refresh_column_widths())
        self._model.rowsRemoved.connect(lambda *_: self._table.refresh_column_widths())

    # ------------------------------------------------------------------
    @property
    def model(self) -> EventTableModel:
        return self._model

    @property
    def rows(self) -> List[Tuple]:
        return self._model.rows()

    @property
    def has_outer(self) -> bool:
        return self._model.has_outer()

    # ------------------------------------------------------------------
    def set_events(
        self,
        data: Iterable[Tuple[str, float, float, Optional[float], Optional[int]]],
        *,
        has_outer_diameter: bool,
    ) -> None:
        self._model.set_events(list(data), has_outer_diameter=has_outer_diameter)
        self._table.apply_theme()
        self.rows_changed.emit()

    def clear(self) -> None:
        self._model.clear()
        self._table.apply_theme()
        self.rows_changed.emit()

    def to_dataframe(self) -> pd.DataFrame:
        return self._model.to_dataframe()

    def insert_row(self, index: int, row: EventRow) -> None:
        self._model.insert_row(index, row)
        self.rows_changed.emit()

    def append_row(self, row: EventRow) -> None:
        self._model.append_row(row)
        self.rows_changed.emit()

    def remove_row(self, index: int) -> EventRow:
        removed = self._model.remove_row(index)
        self.rows_changed.emit()
        return removed

    def update_row(self, index: int, row: EventRow) -> None:
        self._model.update_row(index, row)
        self.rows_changed.emit()
