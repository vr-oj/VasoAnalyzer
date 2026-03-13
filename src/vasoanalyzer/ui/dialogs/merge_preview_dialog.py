# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

"""Merge Preview Dialog — lets the user reorder and confirm segments before merging."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class MergePreviewDialog(QDialog):
    """Preview and reorder trace files before merging into a single dataset."""

    def __init__(
        self,
        trace_paths: list[str],
        events_paths: list[str | None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Merge Preview")
        self.setModal(True)
        self.resize(750, 420)

        # Internal state
        self._items: list[dict] = []
        for i, tp in enumerate(trace_paths):
            ep = events_paths[i] if events_paths and i < len(events_paths) else None
            self._items.append({"trace": tp, "events": ep})

        self.merged_name: str = ""
        self.accepted_order: list[dict] | None = None

        self._build_ui()
        self._populate_table()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Title
        title = QLabel("Merge Segments", self)
        title.setStyleSheet("font-weight: 600; font-size: 16px;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Drag rows or use the buttons to set the correct order. "
            "Segments will be concatenated top-to-bottom.",
            self,
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Table
        self._table = QTableWidget(self)
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels(["#", "Trace File", "Events File"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._table.setDragEnabled(True)
        self._table.setAcceptDrops(True)
        self._table.setDropIndicatorShown(True)
        hdr = self._table.horizontalHeader()
        if hdr is not None:
            hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table)

        # Move buttons
        btn_row = QHBoxLayout()
        self._up_btn = QPushButton("▲ Move Up", self)
        self._down_btn = QPushButton("▼ Move Down", self)
        self._sort_btn = QPushButton("Sort by Name", self)
        btn_row.addWidget(self._up_btn)
        btn_row.addWidget(self._down_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._sort_btn)
        layout.addLayout(btn_row)

        self._up_btn.clicked.connect(self._move_up)
        self._down_btn.clicked.connect(self._move_down)
        self._sort_btn.clicked.connect(self._sort_by_name)

        # Name field
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Dataset name:", self))
        default = Path(self._items[0]["trace"]).stem if self._items else "Merged"
        self._name_edit = QLineEdit(default, self)
        name_row.addWidget(self._name_edit)
        layout.addLayout(name_row)

        # Dialog buttons
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    def _populate_table(self) -> None:
        self._table.setRowCount(len(self._items))
        for i, item in enumerate(self._items):
            self._set_row(i, item)

    def _set_row(self, row: int, item: dict) -> None:
        idx_item = QTableWidgetItem(str(row + 1))
        idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 0, idx_item)

        trace_item = QTableWidgetItem(os.path.basename(item["trace"]))
        trace_item.setToolTip(item["trace"])
        trace_item.setFlags(trace_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 1, trace_item)

        ev = item.get("events")
        ev_text = os.path.basename(ev) if ev else "—"
        ev_item = QTableWidgetItem(ev_text)
        if ev:
            ev_item.setToolTip(ev)
        ev_item.setFlags(ev_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 2, ev_item)

    def _refresh_numbers(self) -> None:
        for i in range(self._table.rowCount()):
            item = self._table.item(i, 0)
            if item is not None:
                item.setText(str(i + 1))

    # ------------------------------------------------------------------
    # Reordering
    # ------------------------------------------------------------------

    def _selected_row(self) -> int | None:
        sel = self._table.selectionModel()
        if sel is None:
            return None
        rows = sel.selectedRows()
        return rows[0].row() if rows else None

    def _move_up(self) -> None:
        row = self._selected_row()
        if row is None or row <= 0:
            return
        self._items[row - 1], self._items[row] = self._items[row], self._items[row - 1]
        self._populate_table()
        self._table.selectRow(row - 1)

    def _move_down(self) -> None:
        row = self._selected_row()
        if row is None or row >= len(self._items) - 1:
            return
        self._items[row], self._items[row + 1] = self._items[row + 1], self._items[row]
        self._populate_table()
        self._table.selectRow(row + 1)

    def _sort_by_name(self) -> None:
        self._items.sort(key=lambda x: Path(x["trace"]).name)
        self._populate_table()

    # ------------------------------------------------------------------
    # Accept
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            self._name_edit.setFocus()
            return
        self.merged_name = name
        self.accepted_order = list(self._items)
        self.accept()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def ordered_trace_paths(self) -> list[str]:
        if self.accepted_order is None:
            return [item["trace"] for item in self._items]
        return [item["trace"] for item in self.accepted_order]

    def ordered_events_paths(self) -> list[str | None]:
        items = self.accepted_order if self.accepted_order is not None else self._items
        return [item.get("events") for item in items]
