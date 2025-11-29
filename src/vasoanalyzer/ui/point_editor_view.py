"""GraphPad-style point editor dialog."""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import vasoanalyzer.ui.theme as theme
from vasoanalyzer.ui.point_editor_session import PointEditorSession, SessionSummary


def _format_float(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:.6g}"


def _parse_modifiers(key: str | None) -> tuple[bool, bool]:
    """Return (additive, toggle) flags given a Matplotlib key descriptor."""

    if not key:
        return False, False
    key_lower = key.lower()
    additive = "shift" in key_lower
    toggle = ("control" in key_lower) or ("cmd" in key_lower) or ("meta" in key_lower)
    return additive, toggle


class PointEditorDialog(QDialog):
    """Interactive dialog that previews manual point edits."""

    def __init__(self, session: PointEditorSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Point Editor – {session.channel_label}")
        self.setModal(True)
        self.session = session
        self._committed_actions: tuple = tuple()
        self._summary: SessionSummary | None = None
        self._updating_table_selection = False
        self._drag_origin: tuple[float, float, str, float, float] | None = None

        self._visible_indices = self.session.visible_indices()
        self._visible_times = self.session.visible_times()
        self._visible_raw = self.session.visible_raw()

        self._build_ui()
        self._connect_session_signals()
        self._refresh_all()

    # ------------------------------------------------------------------ UI setup
    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        plot_container = self._build_plot_panel()
        layout.addWidget(plot_container, stretch=2)

        side_panel = self._build_side_panel()
        layout.addWidget(side_panel, stretch=1)

        self.resize(1100, 620)

    def _build_plot_panel(self) -> QWidget:
        container = QWidget(self)
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(6)

        self.figure = Figure(
            figsize=(6.0, 4.0),
            dpi=120,
            facecolor=theme.CURRENT_THEME.get("window_bg", "#FFFFFF"),
        )
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vbox.addWidget(self.canvas, stretch=1)

        self.ax = self.figure.add_subplot(111)
        self.ax.set_facecolor(theme.CURRENT_THEME.get("plot_bg", "#FFFFFF"))
        self.ax.grid(True, color=theme.CURRENT_THEME.get("grid_color", "#D4D4D4"))
        self.ax.set_xlabel("Time (s)")
        label = "Inner Diameter (µm)" if self.session.channel == "inner" else "Outer Diameter (µm)"
        self.ax.set_ylabel(label)

        raw_color = theme.CURRENT_THEME.get("text_disabled", "#9AA3B4")
        preview_color = theme.CURRENT_THEME.get("accent", "#1976D2")
        selection_color = theme.CURRENT_THEME.get("accent_fill", "#E64A19")

        times = self._visible_times
        raw = self._visible_raw
        clean = self.session.visible_clean()

        self._raw_line = self.ax.plot(
            times, raw, color=raw_color, linewidth=1.0, alpha=0.85, label="Raw"
        )[0]
        self._preview_line = self.ax.plot(
            times, clean, color=preview_color, linewidth=1.8, label="Preview"
        )[0]
        self._selected_scatter = self.ax.scatter(
            [],
            [],
            s=36,
            color=selection_color,
            edgecolors="#333333",
            linewidths=0.6,
            zorder=5,
        )

        self.ax.legend(loc="upper right", frameon=False)
        self.canvas.mpl_connect("button_press_event", self._on_plot_press)
        self.canvas.mpl_connect("button_release_event", self._on_plot_release)

        self.status_label = QLabel("", container)
        self.status_label.setObjectName("PointEditorStatus")
        vbox.addWidget(self.status_label, stretch=0)

        return container

    def _build_side_panel(self) -> QWidget:
        container = QWidget(self)
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        self.table = QTableWidget(container)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Idx", "Time (s)", "Raw", "Preview"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        header = self.table.horizontalHeader()
        for col in range(self.table.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setStretchLastSection(False)
        grid_color = theme.CURRENT_THEME.get("grid_color", "#666666")
        self.table.setStyleSheet(f"QTableWidget {{ gridline-color: {grid_color}; }}")
        grid.addWidget(self.table, 0, 0, 1, 3)

        method_label = QLabel("Connect Method", container)
        self.method_combo = QComboBox(container)
        self.method_combo.addItems(["Linear", "Slope-preserving cubic"])
        self.method_combo.setCurrentIndex(0 if self.session.connect_method == "linear" else 1)
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        grid.addWidget(method_label, 1, 0, 1, 1)
        grid.addWidget(self.method_combo, 1, 1, 1, 2)

        self.delete_btn = QPushButton("Delete (NaN)", container)
        self.delete_btn.clicked.connect(self._on_delete)
        self.connect_btn = QPushButton("Connect Across", container)
        self.connect_btn.clicked.connect(self._on_connect)
        self.restore_btn = QPushButton("Restore", container)
        self.restore_btn.clicked.connect(self._on_restore)

        action_row = QHBoxLayout()
        action_row.addWidget(self.delete_btn)
        action_row.addWidget(self.connect_btn)
        action_row.addWidget(self.restore_btn)
        grid.addLayout(action_row, 2, 0, 1, 3)

        self.undo_btn = QPushButton("Undo", container)
        self.undo_btn.clicked.connect(self._on_undo)
        self.redo_btn = QPushButton("Redo", container)
        self.redo_btn.clicked.connect(self._on_redo)

        stack_row = QHBoxLayout()
        stack_row.addWidget(self.undo_btn)
        stack_row.addWidget(self.redo_btn)
        grid.addLayout(stack_row, 3, 0, 1, 3)

        self.apply_btn = QPushButton("Apply && Close", container)
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self._on_apply)
        self.cancel_btn = QPushButton("Cancel", container)
        self.cancel_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(self.cancel_btn)
        grid.addLayout(buttons, 4, 0, 1, 3)

        return container

    # ------------------------------------------------------------------ session integration
    def _connect_session_signals(self) -> None:
        self.session.data_changed.connect(self._on_session_data_changed)
        self.session.selection_changed.connect(self._on_session_selection_changed)
        self.session.undo_redo_changed.connect(self._on_session_stacks_changed)
        self.session.warning_emitted.connect(self._on_session_warning)

    # ------------------------------------------------------------------ refresh helpers
    def _refresh_all(self) -> None:
        self._populate_table()
        self._update_plot_data()
        self._update_selection_visuals()
        self._update_controls()
        self._resize_table_columns()

    def _resize_table_columns(self) -> None:
        """Ensure table columns are wide enough for current contents."""
        if self.table is None:
            return

        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        col_count = self.table.columnCount()
        if col_count <= 0:
            return

        content_width = sum(header.sectionSize(col) for col in range(col_count))
        available = self.table.viewport().width()
        extra = available - content_width
        if extra <= 0:
            return

        base_extra = extra // col_count
        remainder = extra % col_count
        for col in range(col_count):
            add = base_extra + (1 if col < remainder else 0)
            if add > 0:
                header.resizeSection(col, header.sectionSize(col) + add)

    def _populate_table(self) -> None:
        times = self._visible_times
        raw = self._visible_raw
        clean = self.session.visible_clean()
        row_count = len(times)
        self.table.setRowCount(row_count)
        self._row_to_index: list[int] = []
        self._index_to_row: dict[int, int] = {}
        for row in range(row_count):
            idx = int(self._visible_indices[row])
            self._row_to_index.append(idx)
            self._index_to_row[idx] = row

            idx_item = QTableWidgetItem(str(idx))
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable)
            time_item = QTableWidgetItem(_format_float(times[row]))
            time_item.setFlags(time_item.flags() & ~Qt.ItemIsEditable)
            raw_item = QTableWidgetItem(_format_float(raw[row]))
            raw_item.setFlags(raw_item.flags() & ~Qt.ItemIsEditable)
            clean_item = QTableWidgetItem(_format_float(clean[row]))
            clean_item.setFlags(clean_item.flags() & ~Qt.ItemIsEditable)

            self.table.setItem(row, 0, idx_item)
            self.table.setItem(row, 1, time_item)
            self.table.setItem(row, 2, raw_item)
            self.table.setItem(row, 3, clean_item)
        self._resize_table_columns()

    def _update_plot_data(self) -> None:
        times = self._visible_times
        raw = self._visible_raw
        clean = self.session.visible_clean()
        self._preview_line.set_data(times, clean)
        self._raw_line.set_data(times, raw)
        if times.size:
            xmin, xmax = float(times[0]), float(times[-1])
            span = xmax - xmin
            if span <= 0:
                span = max(self.session.time_window[1] - self.session.time_window[0], 1.0)
                xmin = self.session.time_window[0]
                xmax = xmin + span
            self.ax.set_xlim(xmin, xmax)
        finite_clean = clean[np.isfinite(clean)]
        finite_raw = raw[np.isfinite(raw)]
        combined = (
            np.concatenate([finite_clean, finite_raw])
            if finite_raw.size and finite_clean.size
            else (finite_clean if finite_clean.size else finite_raw)
        )
        if combined.size:
            ymin = float(np.min(combined))
            ymax = float(np.max(combined))
            if ymin == ymax:
                delta = abs(ymin) * 0.05 if abs(ymin) > 1e-6 else 0.1
                ymin -= delta
                ymax += delta
            else:
                pad = (ymax - ymin) * 0.08
                ymin -= pad
                ymax += pad
            self.ax.set_ylim(ymin, ymax)
        self.canvas.draw_idle()

    def _update_preview_column(self) -> None:
        clean = self.session.visible_clean()
        for row, value in enumerate(clean):
            item = self.table.item(row, 3)
            if item is not None:
                item.setText(_format_float(float(value)))
        self._resize_table_columns()

    def _update_selection_visuals(self) -> None:
        selected = self.session.selection()
        if not selected:
            self._selected_scatter.set_offsets(np.empty((0, 2)))
        else:
            coords = []
            for idx in selected:
                row = self._index_to_row.get(idx)
                if row is None:
                    continue
                coords.append((self._visible_times[row], self._visible_raw[row]))
            if coords:
                self._selected_scatter.set_offsets(np.asarray(coords))
            else:
                self._selected_scatter.set_offsets(np.empty((0, 2)))
        self._sync_table_selection()
        self.canvas.draw_idle()

    def _update_status(self) -> None:
        selection_count = len(self.session.selection())
        bounds = self.session.selection_bounds()
        summary = self.session.summary()
        status_parts = [
            f"Selected {selection_count} pts",
            f"Edited {summary.point_count} pts ({summary.percent_of_trace * 100:.3f}%)",
        ]
        if bounds is not None:
            status_parts.append(f"{bounds[0]:.3f}–{bounds[1]:.3f} s")
        status_parts.append(f"Connect: {self.session.connect_method.capitalize()}")
        if self.session.can_undo():
            status_parts.append("Undo available")
        self.status_label.setText(" | ".join(status_parts))

    def _update_controls(self) -> None:
        has_selection = self.session.has_selection()
        self.delete_btn.setEnabled(has_selection)
        self.connect_btn.setEnabled(has_selection)
        self.restore_btn.setEnabled(has_selection)
        self.undo_btn.setEnabled(self.session.can_undo())
        self.redo_btn.setEnabled(self.session.can_redo())
        self._update_status()

    # ------------------------------------------------------------------ session callbacks
    def _on_session_data_changed(self) -> None:
        self._update_preview_column()
        self._update_plot_data()
        self._update_selection_visuals()
        self._update_controls()
        self._resize_table_columns()

    def _on_session_selection_changed(self) -> None:
        self._update_selection_visuals()
        self._update_controls()

    def _on_session_stacks_changed(self, can_undo: bool, can_redo: bool) -> None:
        self.undo_btn.setEnabled(can_undo)
        self.redo_btn.setEnabled(can_redo)
        self._update_status()

    def _on_session_warning(self, message: str) -> None:
        QMessageBox.warning(self, "Point Editor", message)

    # ------------------------------------------------------------------ plot interaction
    def _on_plot_press(self, event) -> None:
        if (
            event.inaxes != self.ax
            or event.button != 1
            or event.xdata is None
            or event.ydata is None
        ):
            self._drag_origin = None
            return
        self._drag_origin = (
            float(event.xdata),
            float(event.ydata),
            event.key or "",
            float(getattr(event, "x", 0.0)),
            float(getattr(event, "y", 0.0)),
        )

    def _on_plot_release(self, event) -> None:
        if self._drag_origin is None or event.inaxes != self.ax or event.button != 1:
            return
        x0, y0, key, px0, py0 = self._drag_origin
        if event.xdata is None or event.ydata is None:
            self._drag_origin = None
            return
        x1, y1 = float(event.xdata), float(event.ydata)
        px1 = float(getattr(event, "x", 0.0))
        py1 = float(getattr(event, "y", 0.0))
        if abs(px1 - px0) <= 4 and abs(py1 - py0) <= 4:
            self._select_nearest_point(x1, key)
        else:
            self._select_box(x0, y0, x1, y1, key)
        self._drag_origin = None

    def _select_nearest_point(self, x_data: float, key: str | None) -> None:
        times = self._visible_times
        if times.size == 0:
            return
        idx_local = int(np.argmin(np.abs(times - x_data)))
        idx_global = int(self._visible_indices[idx_local])
        additive, toggle = _parse_modifiers(key)
        self.session.set_selection([idx_global], additive=additive, toggle=toggle)

    def _select_box(self, x0: float, y0: float, x1: float, y1: float, key: str | None) -> None:
        xmin, xmax = sorted((x0, x1))
        ymin, ymax = sorted((y0, y1))
        indices: list[int] = []
        times = self._visible_times
        raw = self._visible_raw
        for local_idx, (tx, ty) in enumerate(zip(times, raw, strict=False)):
            if xmin <= tx <= xmax and ymin <= ty <= ymax:
                indices.append(int(self._visible_indices[local_idx]))
        if not indices:
            return
        additive, toggle = _parse_modifiers(key)
        self.session.set_selection(indices, additive=additive, toggle=toggle)

    # ------------------------------------------------------------------ table interaction
    def _on_table_selection_changed(self) -> None:
        if self._updating_table_selection:
            return
        rows = self.table.selectionModel().selectedRows()
        indices = [int(self._row_to_index[row.row()]) for row in rows]
        self.session.set_selection(indices, additive=False)

    def _sync_table_selection(self) -> None:
        self._updating_table_selection = True
        try:
            self.table.clearSelection()
            for idx in self.session.selection():
                row = self._index_to_row.get(idx)
                if row is not None:
                    self.table.selectRow(row)
        finally:
            self._updating_table_selection = False

    # ------------------------------------------------------------------ button handlers
    def _on_method_changed(self, index: int) -> None:
        method = "linear" if index == 0 else "cubic"
        self.session.connect_method = method
        self._update_status()

    def _on_delete(self) -> None:
        action = self.session.delete_selection()
        if action is None:
            return
        self._update_controls()

    def _on_connect(self) -> None:
        method = "linear" if self.method_combo.currentIndex() == 0 else "cubic"
        action = self.session.connect_selection(method=method)
        if action is None:
            return
        self._update_controls()

    def _on_restore(self) -> None:
        action = self.session.restore_selection()
        if action is None:
            return
        self._update_controls()

    def _on_undo(self) -> None:
        if self.session.undo() is None:
            return
        self._update_controls()

    def _on_redo(self) -> None:
        if self.session.redo() is None:
            return
        self._update_controls()

    def _on_apply(self) -> None:
        summary = self.session.summary()
        actions = self.session.commit()
        if actions:
            self._committed_actions = actions
            self._summary = summary
        self.accept()

    # ------------------------------------------------------------------ public accessors
    def committed_actions(self) -> tuple:
        return self._committed_actions

    def session_summary(self) -> SessionSummary | None:
        return self._summary
