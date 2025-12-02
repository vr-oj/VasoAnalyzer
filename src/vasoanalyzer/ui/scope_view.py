"""Triggered sweep capture dock."""

from __future__ import annotations

import csv

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vasoanalyzer.core.sweeps import SweepResult, TriggerConfig, compute_sweeps
from vasoanalyzer.core.trace_model import TraceModel
from vasoanalyzer.ui.theme import CURRENT_THEME


class ScopeDock(QDockWidget):
    """Dockable widget that captures triggered sweeps and plots overlays."""

    def __init__(self, parent=None) -> None:
        super().__init__("Scope", parent)
        self.setObjectName("ScopeDock")
        self._model: TraceModel | None = None
        self._last_result: SweepResult | None = None

        self._build_ui()

    # ------------------------------------------------------------------ public API
    def set_trace_model(self, model: TraceModel | None) -> None:
        self._model = model
        has_data = model is not None and model.time_full.size > 0
        self.capture_btn.setEnabled(has_data)
        self.export_btn.setEnabled(False)
        self._last_result = None
        self._populate_sources()
        if has_data:
            self._update_threshold_hint()
        self._render_result()

    # ------------------------------------------------------------------ UI construction
    def _build_ui(self) -> None:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        controls = QGridLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setHorizontalSpacing(8)
        controls.setVerticalSpacing(4)

        row = 0
        self.source_combo = QComboBox()
        controls.addWidget(QLabel("Trigger Source"), row, 0)
        controls.addWidget(self.source_combo, row, 1)

        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["Rising", "Falling"])
        row += 1
        controls.addWidget(QLabel("Direction"), row, 0)
        controls.addWidget(self.direction_combo, row, 1)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setSuffix(" µm")
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setRange(-10000.0, 10000.0)
        self.threshold_spin.setSingleStep(0.5)
        row += 1
        controls.addWidget(QLabel("Threshold"), row, 0)
        controls.addWidget(self.threshold_spin, row, 1)

        self.pre_spin = QDoubleSpinBox()
        self.pre_spin.setRange(0.0, 60.0)
        self.pre_spin.setDecimals(2)
        self.pre_spin.setSingleStep(0.1)
        self.pre_spin.setSuffix(" s")
        self.pre_spin.setValue(1.0)
        row += 1
        controls.addWidget(QLabel("Pre window"), row, 0)
        controls.addWidget(self.pre_spin, row, 1)

        self.post_spin = QDoubleSpinBox()
        self.post_spin.setRange(0.0, 60.0)
        self.post_spin.setDecimals(2)
        self.post_spin.setSingleStep(0.1)
        self.post_spin.setSuffix(" s")
        self.post_spin.setValue(1.0)
        row += 1
        controls.addWidget(QLabel("Post window"), row, 0)
        controls.addWidget(self.post_spin, row, 1)

        self.min_interval_spin = QDoubleSpinBox()
        self.min_interval_spin.setRange(0.0, 120.0)
        self.min_interval_spin.setDecimals(2)
        self.min_interval_spin.setSingleStep(0.1)
        self.min_interval_spin.setSuffix(" s")
        self.min_interval_spin.setValue(0.5)
        row += 1
        controls.addWidget(QLabel("Min interval"), row, 0)
        controls.addWidget(self.min_interval_spin, row, 1)

        layout.addLayout(controls)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(8)
        self.overlay_check = QCheckBox("Overlay sweeps")
        self.overlay_check.setChecked(True)
        self.average_check = QCheckBox("Show average")
        self.average_check.setChecked(True)
        toggle_row.addWidget(self.overlay_check)
        toggle_row.addWidget(self.average_check)
        toggle_row.addStretch(1)
        layout.addLayout(toggle_row)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)
        self.capture_btn = QPushButton("Capture")
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setEnabled(False)
        buttons_row.addWidget(self.capture_btn)
        buttons_row.addWidget(self.export_btn)
        buttons_row.addStretch(1)
        layout.addLayout(buttons_row)

        self.figure = Figure(
            figsize=(4.5, 3.0),
            dpi=120,
            facecolor=CURRENT_THEME.get("window_bg", "#FFFFFF"),
        )
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_facecolor(CURRENT_THEME.get("window_bg", "#FFFFFF"))
        self.ax.grid(True, color=CURRENT_THEME.get("grid_color", "#CCCCCC"))
        self.ax.set_xlabel("Time relative to trigger (s)")
        self.ax.set_ylabel("Diameter (µm)")
        layout.addWidget(self.canvas, 1)

        self.summary_label = QLabel("No sweeps captured")
        self.summary_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.summary_label)

        self.setWidget(container)

        # Wiring
        self.capture_btn.clicked.connect(self._on_capture)
        self.export_btn.clicked.connect(self._export_csv)
        self.overlay_check.toggled.connect(self._render_result)
        self.average_check.toggled.connect(self._render_result)
        self.source_combo.currentIndexChanged.connect(self._update_threshold_hint)

    def apply_theme(self) -> None:
        """Reapply theme colors to the scope plot."""

        bg = CURRENT_THEME.get("window_bg", "#FFFFFF")
        grid = CURRENT_THEME.get("grid_color", "#CCCCCC")
        text = CURRENT_THEME.get("text", "#000000")

        self.figure.set_facecolor(bg)
        self.ax.set_facecolor(bg)
        self.ax.tick_params(colors=text)
        self.ax.xaxis.label.set_color(text)
        self.ax.yaxis.label.set_color(text)
        self.ax.title.set_color(text)
        self.ax.grid(True, color=grid)
        self.canvas.draw_idle()

    # ------------------------------------------------------------------ helpers
    def _populate_sources(self) -> None:
        current = self.source_combo.currentData(Qt.UserRole)
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem("Inner Diameter", "inner")
        if self._model is not None and self._model.outer_full is not None:
            self.source_combo.addItem("Outer Diameter", "outer")
        self.source_combo.blockSignals(False)
        if current is not None:
            index = self.source_combo.findData(current, role=Qt.UserRole)
            if index >= 0:
                self.source_combo.setCurrentIndex(index)

    def _update_threshold_hint(self) -> None:
        if self._model is None:
            return
        source = self.source_combo.currentData(Qt.UserRole)
        if source == "outer":
            data = self._model.outer_full
            if data is None:
                data = self._model.inner_full
        else:
            data = self._model.inner_full
        finite = data[np.isfinite(data)]
        if finite.size:
            median = float(np.median(finite))
            self.threshold_spin.blockSignals(True)
            self.threshold_spin.setValue(median)
            self.threshold_spin.blockSignals(False)

    def _on_capture(self) -> None:
        if self._model is None:
            QMessageBox.information(self, "No Trace", "Load a trace to capture sweeps.")
            return
        try:
            config = TriggerConfig(
                component=str(self.source_combo.currentData(Qt.UserRole) or "inner"),
                threshold=float(self.threshold_spin.value()),
                direction="rising" if self.direction_combo.currentIndex() == 0 else "falling",
                pre_window=float(self.pre_spin.value()),
                post_window=float(self.post_spin.value()),
                min_interval=float(self.min_interval_spin.value()),
            )
            result = compute_sweeps(self._model, config)
        except ValueError as exc:
            QMessageBox.warning(self, "Sweep capture failed", str(exc))
            return

        self._last_result = result
        self.export_btn.setEnabled(result.count > 0)
        self._render_result()

    def _render_result(self) -> None:
        self.ax.clear()
        self.ax.set_facecolor(CURRENT_THEME.get("window_bg", "#FFFFFF"))
        self.ax.grid(True, color=CURRENT_THEME.get("grid_color", "#CCCCCC"))
        self.ax.axvline(0.0, color="#707070", linestyle="--", linewidth=1.0, alpha=0.6)
        self.ax.set_xlabel("Time relative to trigger (s)")
        self.ax.set_ylabel("Diameter (µm)")

        if not self._last_result or self._last_result.count == 0:
            self.summary_label.setText("No sweeps captured")
            self.canvas.draw_idle()
            return

        result = self._last_result
        time = result.relative_time
        palette_inner = CURRENT_THEME.get("cursor_a", "#3366FF")
        palette_outer = CURRENT_THEME.get("cursor_b", "#FF6B3D")

        if self.overlay_check.isChecked():
            for sweep in result.inner_sweeps:
                self.ax.plot(time, sweep, color=palette_inner, alpha=0.25, linewidth=0.8)
            if result.has_outer():
                for sweep in result.outer_sweeps:
                    self.ax.plot(time, sweep, color=palette_outer, alpha=0.25, linewidth=0.8)

        labels = []
        if self.average_check.isChecked():
            if result.average_inner is not None:
                self.ax.plot(time, result.average_inner, color=palette_inner, linewidth=2.0)
                labels.append(("Inner", palette_inner))
            if result.average_outer is not None:
                self.ax.plot(time, result.average_outer, color=palette_outer, linewidth=2.0)
                labels.append(("Outer", palette_outer))
        if labels:
            handles = [self.ax.plot([], [], color=color, linewidth=2.0)[0] for _, color in labels]
            self.ax.legend(handles, [label for label, _ in labels], loc="upper right")

        self.summary_label.setText(f"Captured {result.count} sweeps")
        self.canvas.draw_idle()

    def _export_csv(self) -> None:
        if not self._last_result or self._last_result.count == 0:
            QMessageBox.information(self, "Nothing to export", "Capture sweeps before exporting.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export sweep average",
            "sweep_average.csv",
            "CSV Files (*.csv)",
        )
        if not path:
            return

        result = self._last_result
        header = ["relative_time_s", "inner_avg_um"]
        has_outer = result.average_outer is not None
        if has_outer:
            header.append("outer_avg_um")

        try:
            with open(path, "w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(header)
                for idx, time_val in enumerate(result.relative_time):
                    row = [f"{time_val:.6f}"]
                    if result.average_inner is not None:
                        row.append(f"{result.average_inner[idx]:.6f}")
                    else:
                        row.append("")
                    if has_outer and result.average_outer is not None:
                        row.append(f"{result.average_outer[idx]:.6f}")
                    writer.writerow(row)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return

        QMessageBox.information(self, "Export complete", f"Saved {path}")
